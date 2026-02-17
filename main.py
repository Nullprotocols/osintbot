import os
import json
import logging
import threading
import re
import requests
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from dotenv import load_dotenv
import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Force channels
FORCE_CHANNELS = [
    {"link": os.getenv("FORCE_CHANNEL1_LINK"), "id": int(os.getenv("FORCE_CHANNEL1_ID"))},
    {"link": os.getenv("FORCE_CHANNEL2_LINK"), "id": int(os.getenv("FORCE_CHANNEL2_ID"))},
]

# Log channels mapping (command -> channel_id)
LOG_CHANNELS = {
    "num": int(os.getenv("LOG_CHANNEL_NUM")),
    "ifsc": int(os.getenv("LOG_CHANNEL_IFSC")),
    "email": int(os.getenv("LOG_CHANNEL_EMAIL")),
    "gst": int(os.getenv("LOG_CHANNEL_GST")),
    "vehicle": int(os.getenv("LOG_CHANNEL_VEHICLE")),
    "vchalan": int(os.getenv("LOG_CHANNEL_CHALAN")),
    "pin": int(os.getenv("LOG_CHANNEL_PINCODE")),
    "insta": int(os.getenv("LOG_CHANNEL_INSTAGRAM")),
    "git": int(os.getenv("LOG_CHANNEL_GITHUB")),
    "pak": int(os.getenv("LOG_CHANNEL_PAKISTAN")),
    "ip": int(os.getenv("LOG_CHANNEL_IP")),
    "ffinfo": int(os.getenv("LOG_CHANNEL_FF_INFO")),
    "ffban": int(os.getenv("LOG_CHANNEL_FF_BAN")),
    "tg2num": int(os.getenv("LOG_CHANNEL_TG2NUM")),
    "tginfo": int(os.getenv("LOG_CHANNEL_TG_TO_INFO")),
    "tginfopro": int(os.getenv("LOG_CHANNEL_TGPRO")),
}

# Admin/Owner IDs
ADMIN_IDS = [int(x.strip()) for x in os.getenv("BOT_ADMIN_IDS", "").split(",") if x.strip()]
OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask ऐप (Render के लिए)
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "OSINT Bot is running!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

# ================== डेटाबेस इनिशियलाइज़ ==================
db.init_db()

# ================== यूटिलिटी फंक्शन ==================

def is_user_admin_or_owner(user_id):
    """चेक करें कि यूजर एडमिन या ओनर है (डेटाबेस और एनवायरनमेंट दोनों से)"""
    if user_id == OWNER_ID:
        return True
    if user_id in ADMIN_IDS:
        return True
    user = db.get_user(user_id)
    if user and (user[5] == 1 or user[6] == 1):
        return True
    return False

async def check_force_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """चेक करें कि यूजर दोनों फोर्स चैनल में है या नहीं। अगर नहीं, तो मैसेज भेजें और False लौटाएँ।"""
    user_id = update.effective_user.id
    if is_user_admin_or_owner(user_id):
        return True  # एडमिन/ओनर को फोर्स चैनल की जरूरत नहीं

    not_joined = []
    for channel in FORCE_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(channel["link"])
        except Exception as e:
            logger.error(f"Force channel check error: {e}")
            not_joined.append(channel["link"])  # अगर चेक न कर पाए तो भी ज्वाइन करने को कहें

    if not_joined:
        buttons = []
        for link in not_joined:
            buttons.append([InlineKeyboardButton("🔔 जॉइन करें", url=link)])
        buttons.append([InlineKeyboardButton("✅ जॉइन किया", callback_data="check_joined")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "आपने बॉट का उपयोग करने के लिए निम्नलिखित चैनल जॉइन नहीं किए हैं। कृपया जॉइन करें और फिर 'जॉइन किया' बटन दबाएँ।",
            reply_markup=reply_markup
        )
        return False
    return True

async def check_group_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """अगर प्राइवेट चैट में है तो मैसेज भेजें और False लौटाएँ।"""
    if update.effective_chat.type == "private":
        # एडमिन/ओनर को प्राइवेट में भी चलने दें
        if is_user_admin_or_owner(update.effective_user.id):
            return True
        await update.message.reply_text(
            "🤖 यह बॉट केवल **समूहों (groups)** में काम करता है।\n"
            "यदि आप निजी तौर पर OSINT टूल्स का उपयोग करना चाहते हैं, तो कृपया हमारे दूसरे बॉट का उपयोग करें: @osintfatherNullBot"
        )
        return False
    return True

async def log_to_channel(update: Update, command: str, result: str = ""):
    """कमांड के अनुसार लॉग चैनल पर मैसेज भेजें।"""
    channel_id = LOG_CHANNELS.get(command)
    if not channel_id:
        return
    user = update.effective_user
    chat = update.effective_chat
    message = (
        f"👤 User: {user.full_name} (@{user.username})\n"
        f"🆔 ID: {user.id}\n"
        f"💬 Chat: {chat.title if chat.title else chat.type}\n"
        f"📝 Command: /{command} {' '.join(update.message.text.split()[1:])}\n"
        f"⏱ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 Result snippet: {result[:200]}"
    )
    try:
        await context.bot.send_message(chat_id=channel_id, text=message)
    except Exception as e:
        logger.error(f"Failed to log to channel {channel_id}: {e}")

def call_api(url):
    """किसी भी API को कॉल करके JSON रिस्पॉन्स लौटाता है।"""
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"API Error: HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}

def clean_number_api_output(data):
    """API_NUM के आउटपुट से अवांछित ब्रांडिंग हटाता है।"""
    banned_phrases = [
        'dm to buy', 'owner', '@kon_hu_mai', 'Ruk ja bhencho itne m kya unlimited request lega?? Paid lena h to bolo 100-400₹ @Simpleguy444',
        '@patelkrish_99', 'patelkrish_99', 't.me/anshapi', 'anshapi', '"@Kon_Hu_Mai"', 'Dm to buy access', '"Dm to buy access"', 'Kon_Hu_Mai'
    ]
    
    def clean_string(s):
        if isinstance(s, str):
            for phrase in banned_phrases:
                s = s.replace(phrase, '')
            s = re.sub(r'\s+', ' ', s).strip()
            return s
        return s

    def clean_obj(obj):
        if isinstance(obj, dict):
            return {k: clean_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_obj(item) for item in obj]
        elif isinstance(obj, str):
            return clean_string(obj)
        else:
            return obj

    return clean_obj(data)

def format_json_output(api_name, json_data):
    """JSON डेटा को सुंदर स्ट्रिंग में बदलता है, और फुटर में ब्रांडिंग जोड़ता है।"""
    pretty_json = json.dumps(json_data, indent=2, ensure_ascii=False)
    footer = "\n\n---\n👨‍💻 developer: @Nullprotocol_X\n⚡ powered_by: NULL PROTOCOL"
    return f"```json\n{pretty_json}\n```{footer}"

# ================== कमांड हैंडलर ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    if not await check_group_only(update, context):
        return
    if not await check_force_channels(update, context):
        return
    await update.message.reply_text(
        f"नमस्ते {user.first_name}! मैं OSINT बॉट हूँ। /help से सभी कमांड देखें।"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_group_only(update, context):
        return
    if not await check_force_channels(update, context):
        return
    help_text = """
    उपलब्ध कमांड:
    /num <10 अंकों का नंबर> - मोबाइल नंबर की जानकारी
    /tg2num <टेलीग्राम ID> - टेलीग्राम ID से नंबर
    /vehicle <गाड़ी नंबर> - वाहन मालिक की जानकारी
    /vchalan <गाड़ी नंबर> - वाहन चालान की जानकारी
    /ip <IP एड्रेस> - IP जानकारी
    /email <ईमेल> - ईमेल जानकारी
    /ffinfo <FF UID> - फ्री फायर प्रोफाइल
    /ffban <FF UID> - फ्री फायर बान स्टेटस
    /pin <पिनकोड> - पिनकोड विवरण
    /ifsc <IFSC कोड> - बैंक शाखा जानकारी
    /gst <GST नंबर> - GST जानकारी
    /insta <इंस्टाग्राम यूजरनेम> - इंस्टाग्राम जानकारी
    /tginfo <@टेलीग्राम यूजरनेम> - टेलीग्राम यूजर जानकारी
    /tginfopro <टेलीग्राम ID> - टेलीग्राम प्रो जानकारी
    /git <गिटहब यूजरनेम> - गिटहब जानकारी
    /pak <पाकिस्तान नंबर> - पाकिस्तान नंबर जानकारी
    """
    await update.message.reply_text(help_text)

# OSINT कमांड्स के लिए जेनेरिक हैंडलर
async def handle_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE, api_url_template, command_name, arg_name="query"):
    if not await check_group_only(update, context):
        return
    if not await check_force_channels(update, context):
        return

    if not context.args:
        await update.message.reply_text(f"कृपया {arg_name} प्रदान करें।")
        return

    user_input = context.args[0]
    url = api_url_template + user_input

    data = call_api(url)

    # अगर नंबर API है तो ब्रांडिंग हटाएँ
    if 'num-free-rootx' in api_url_template:
        data = clean_number_api_output(data)

    # लॉग डेटाबेस में जोड़ें
    db.log_command(update.effective_user.id, command_name, str(data)[:200])

    # लॉग चैनल पर भेजें
    await log_to_channel(update, command_name, str(data)[:200])

    formatted = format_json_output(command_name, data)

    # कॉपी बटन
    keyboard = [[InlineKeyboardButton("📋 JSON कॉपी करें", callback_data=f"copy_{url}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        formatted,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

# सभी OSINT कमांड्स को परिभाषित करें
async def num_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://num-free-rootx-jai-shree-ram-14-day.vercel.app/?key=lundkinger&number=", "num", "10 digit number")

async def tg2num_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://tg2num-owner-api.vercel.app/?userid=", "tg2num", "Telegram ID")

async def vehicle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://vehicle-info-aco-api.vercel.app/info?vehicle=", "vehicle", "vehicle number")

async def vchalan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://api.b77bf911.workers.dev/vehicle?registration=", "vchalan", "vehicle number")

async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/ip?ip=", "ip", "IP address")

async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/email?mail=", "email", "email address")

async def ffinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://official-free-fire-info.onrender.com/player-info?key=DV_M7-INFO_API&uid=", "ffinfo", "Free Fire UID")

async def ffban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/ff-ban?uid=", "ffban", "Free Fire UID")

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://api.postalpincode.in/pincode/", "pin", "pincode")

async def ifsc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/ifsc?ifsc=", "ifsc", "IFSC code")

async def gst_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://api.b77bf911.workers.dev/gst?number=", "gst", "GST number")

async def insta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://mkhossain.alwaysdata.net/instanum.php?username=", "insta", "Instagram username")

async def tginfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://openosintx.vippanel.in/tgusrinfo.php?key=OpenOSINTX-FREE&user=", "tginfo", "Telegram username with @")

async def tginfopro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://api.b77bf911.workers.dev/telegram?user=", "tginfopro", "Telegram ID")

async def git_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/github?username=", "git", "GitHub username")

async def pak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_api_command(update, context, "https://abbas-apis.vercel.app/api/pakistan?number=", "pak", "Pakistan number")

# ================== कॉलबैक हैंडलर (JSON कॉपी + चेक जॉइन) ==================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_joined":
        # फिर से चेक करें
        user_id = query.from_user.id
        not_joined = []
        for channel in FORCE_CHANNELS:
            try:
                member = await context.bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(channel["link"])
            except:
                not_joined.append(channel["link"])
        if not_joined:
            await query.edit_message_text("आप अभी भी सभी चैनल में नहीं हैं। कृपया जॉइन करें और पुनः प्रयास करें।")
        else:
            await query.edit_message_text("धन्यवाद! अब आप बॉट का उपयोग कर सकते हैं। कृपया /start दबाएँ।")
        return

    if query.data.startswith("copy_"):
        url = query.data[5:]
        data = call_api(url)
        if 'num-free-rootx' in url:
            data = clean_number_api_output(data)
        plain_json = json.dumps(data, indent=2, ensure_ascii=False)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"```json\n{plain_json}\n```",
            parse_mode=ParseMode.MARKDOWN
        )

# ================== एडमिन कमांड्स ==================

def admin_only(func):
    """डेकोरेटर: केवल एडमिन/ओनर को ही कमांड एक्सेस दे"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not is_user_admin_or_owner(update.effective_user.id):
            await update.message.reply_text("⛔ आपके पास इस कमांड का उपयोग करने की अनुमति नहीं है।")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ब्रॉडकास्ट मैसेज सभी यूजर्स को भेजें। टेक्स्ट, फोटो, वीडियो, पोल आदि सपोर्ट करता है।"""
    # यूजर्स की लिस्ट लें
    users = db.get_all_users(limit=1000000)  # सभी यूजर्स (बेहतर होगा batch में)
    if not users:
        await update.message.reply_text("कोई यूजर नहीं है।")
        return

    # मैसेज टाइप पहचानें: अगर रिप्लाई किया गया है तो उसी मीडिया को फॉरवर्ड करें
    reply = update.message.reply_to_message
    if reply:
        # रिप्लाई की गई मैसेज को फॉरवर्ड करें
        success = 0
        failed = 0
        for user in users:
            try:
                await reply.forward(chat_id=user[0])
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"Broadcast to {user[0]} failed: {e}")
        await update.message.reply_text(f"✅ ब्रॉडकास्ट पूरा हुआ!\nसफल: {success}\nअसफल: {failed}")
    else:
        # टेक्स्ट मैसेज
        if not context.args:
            await update.message.reply_text("कृपया ब्रॉडकास्ट टेक्स्ट दें या किसी मैसेज को रिप्लाई करें।")
            return
        text = " ".join(context.args)
        success = 0
        failed = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user[0], text=text)
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"Broadcast to {user[0]} failed: {e}")
        await update.message.reply_text(f"✅ ब्रॉडकास्ट पूरा हुआ!\nसफल: {success}\nअसफल: {failed}")

@admin_only
async def dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """किसी एक यूजर को डायरेक्ट मैसेज भेजें। /dm ID मैसेज"""
    if len(context.args) < 2:
        await update.message.reply_text("उपयोग: /dm user_id मैसेज")
        return
    try:
        user_id = int(context.args[0])
        msg = " ".join(context.args[1:])
        await context.bot.send_message(chat_id=user_id, text=msg)
        await update.message.reply_text(f"✅ मैसेज {user_id} को भेज दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ भेजने में विफल: {e}")

@admin_only
async def bulkdm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """एक साथ कई यूजर्स को मैसेज भेजें। /bulkdm ID1,ID2,ID3 मैसेज"""
    if len(context.args) < 2:
        await update.message.reply_text("उपयोग: /bulkdm ID1,ID2,ID3 मैसेज")
        return
    ids_part = context.args[0]
    msg = " ".join(context.args[1:])
    id_list = [int(x.strip()) for x in ids_part.split(",") if x.strip().isdigit()]
    if not id_list:
        await update.message.reply_text("कोई वैलिड ID नहीं मिली।")
        return
    success = 0
    failed = 0
    for uid in id_list:
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            success += 1
        except:
            failed += 1
    await update.message.reply_text(f"✅ परिणाम: सफल: {success}, असफल: {failed}")

@admin_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("उपयोग: /ban user_id")
        return
    try:
        user_id = int(context.args[0])
        db.ban_user(user_id)
        await update.message.reply_text(f"✅ यूजर {user_id} को बैन कर दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("उपयोग: /unban user_id")
        return
    try:
        user_id = int(context.args[0])
        db.unban_user(user_id)
        await update.message.reply_text(f"✅ यूजर {user_id} का बैन हटा दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def deleteuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("उपयोग: /deleteuser user_id")
        return
    try:
        user_id = int(context.args[0])
        db.delete_user(user_id)
        await update.message.reply_text(f"✅ यूजर {user_id} डेटाबेस से हटा दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def searchuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("उपयोग: /searchuser क्वेरी")
        return
    query = " ".join(context.args)
    users = db.search_users(query)
    if not users:
        await update.message.reply_text("कोई यूजर नहीं मिला।")
        return
    text = "🔍 **खोज परिणाम:**\n"
    for u in users:
        text += f"👤 {u[1]} ({u[2]}) | ID: `{u[0]}` | बैन: {u[5]} | एडमिन: {u[6]}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    limit = 10
    offset = (page - 1) * limit
    users = db.get_all_users(limit=limit, offset=offset)
    total = db.count_users()
    if not users:
        await update.message.reply_text("कोई यूजर नहीं।")
        return
    text = f"👥 **यूजर्स (पेज {page})** - कुल: {total}\n"
    for u in users:
        text += f"👤 {u[2]} (@{u[1]}) | ID: `{u[0]}` | जॉइन: {u[4][:10]}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def recentusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    users = db.get_recent_users(days)
    text = f"📅 **पिछले {days} दिनों में नए यूजर्स:** {len(users)}\n"
    for u in users[:10]:
        text += f"👤 {u[2]} (@{u[1]}) | {u[4][:10]}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def userlookups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("उपयोग: /userlookups user_id")
        return
    try:
        user_id = int(context.args[0])
        logs = db.get_user_logs(user_id, limit=10)
        if not logs:
            await update.message.reply_text("इस यूजर का कोई लॉग नहीं।")
            return
        text = f"📋 **यूजर {user_id} के हालिया लुकअप:**\n"
        for log in logs:
            text += f"• {log[2]} ({log[3][:19]}) - {log[4][:50]}\n"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # सबसे ज्यादा लुकअप करने वाले यूजर्स
    conn = sqlite3.connect(db.DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT user_id, COUNT(*) as cnt FROM logs GROUP BY user_id ORDER BY cnt DESC LIMIT 10''')
    top = c.fetchall()
    conn.close()
    if not top:
        await update.message.reply_text("कोई डेटा नहीं।")
        return
    text = "🏆 **टॉप 10 यूजर्स (लुकअप काउंट):**\n"
    for i, (uid, cnt) in enumerate(top, 1):
        text += f"{i}. `{uid}` - {cnt} लुकअप\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def inactiveusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = 30
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    users = db.get_inactive_users(days)
    text = f"⏰ **{days} दिनों से निष्क्रिय यूजर्स:** {len(users)}\n"
    for u in users[:10]:
        text += f"👤 {u[2]} (@{u[1]}) | आखिरी जॉइन: {u[4][:10]}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# Statistics commands
@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users, total_banned, total_admins, total_logs = db.get_stats()
    text = (
        f"📊 **बॉट सांख्यिकी:**\n"
        f"👥 कुल यूजर्स: {total_users}\n"
        f"🚫 बैन यूजर्स: {total_banned}\n"
        f"👑 एडमिन: {total_admins}\n"
        f"📝 कुल लुकअप: {total_logs}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def dailystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    stats = db.get_daily_stats(days)
    if not stats:
        await update.message.reply_text("कोई डेटा नहीं।")
        return
    text = f"📅 **पिछले {days} दिनों के लुकअप:**\n"
    for date, cnt in stats:
        text += f"{date}: {cnt} लुकअप\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def lookupstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_lookup_stats()
    if not stats:
        await update.message.reply_text("कोई डेटा नहीं।")
        return
    text = "🔍 **लुकअप कमांड स्टैटिस्टिक्स:**\n"
    for cmd, cnt in stats:
        text += f"/{cmd}: {cnt} बार\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """डेटा का बैकअप CSV के रूप में भेजें।"""
    csv_data = db.backup_to_csv()
    await update.message.reply_document(
        document=io.BytesIO(csv_data.encode()),
        filename=f"users_backup_{datetime.now().strftime('%Y%m%d')}.csv"
    )

@admin_only
async def topref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit = 10
    if context.args and context.args[0].isdigit():
        limit = int(context.args[0])
    top = db.get_top_referrers(limit)
    if not top:
        await update.message.reply_text("कोई रेफरल नहीं।")
        return
    text = f"🏆 **टॉप {limit} रेफरल देने वाले:**\n"
    for ref_id, cnt in top:
        user = db.get_user(ref_id)
        name = user[2] if user else str(ref_id)
        text += f"👤 {name} (ID: {ref_id}) - {cnt} रेफरल\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# Owner commands
@admin_only
async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("केवल ओनर ही एडमिन जोड़ सकता है।")
        return
    if not context.args:
        await update.message.reply_text("उपयोग: /addadmin user_id")
        return
    try:
        user_id = int(context.args[0])
        db.add_admin(user_id)
        await update.message.reply_text(f"✅ यूजर {user_id} को एडमिन बना दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("केवल ओनर ही एडमिन हटा सकता है।")
        return
    if not context.args:
        await update.message.reply_text("उपयोग: /removeadmin user_id")
        return
    try:
        user_id = int(context.args[0])
        db.remove_admin(user_id)
        await update.message.reply_text(f"✅ यूजर {user_id} से एडमिन हटा दिया गया।")
    except Exception as e:
        await update.message.reply_text(f"❌ त्रुटि: {e}")

@admin_only
async def listadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = db.list_admins()
    if not admins:
        await update.message.reply_text("कोई एडमिन नहीं।")
        return
    text = "👑 **एडमिन लिस्ट:**\n"
    for uid, uname in admins:
        text += f"• {uname} (ID: `{uid}`)\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # बेसिक सेटिंग्स दिखाएँ
    text = (
        "⚙️ **बॉट सेटिंग्स:**\n"
        f"• ओनर ID: `{OWNER_ID}`\n"
        f"• एडमिन IDs: {', '.join(map(str, ADMIN_IDS))}\n"
        f"• फोर्स चैनल: {', '.join([c['link'] for c in FORCE_CHANNELS])}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def fulldbbackup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # डेटाबेस फाइल (.db) और CSV भेजें
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("केवल ओनर ही फुल बैकअप ले सकता है।")
        return
    # .db file
    with open(db.DB_FILE, 'rb') as f:
        await update.message.reply_document(document=f, filename=db.DB_FILE)
    # CSV
    csv_data = db.backup_to_csv()
    await update.message.reply_document(
        document=io.BytesIO(csv_data.encode()),
        filename=f"users_backup_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    # Google Sheets link (आपके दिए गए लिंक से)
    await update.message.reply_text(
        "📊 Google Sheets बैकअप:\n"
        "https://docs.google.com/spreadsheets/d/174-LvA9PGzz2tp-ZLbBjbyCiMUPp2ZY7iXci4foQjVo/edit?usp=sharing"
    )

# ================== बॉट सेटअप और थ्रेड ==================

def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()

    # OSINT कमांड्स
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("num", num_command))
    app.add_handler(CommandHandler("tg2num", tg2num_command))
    app.add_handler(CommandHandler("vehicle", vehicle_command))
    app.add_handler(CommandHandler("vchalan", vchalan_command))
    app.add_handler(CommandHandler("ip", ip_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("ffinfo", ffinfo_command))
    app.add_handler(CommandHandler("ffban", ffban_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("ifsc", ifsc_command))
    app.add_handler(CommandHandler("gst", gst_command))
    app.add_handler(CommandHandler("insta", insta_command))
    app.add_handler(CommandHandler("tginfo", tginfo_command))
    app.add_handler(CommandHandler("tginfopro", tginfopro_command))
    app.add_handler(CommandHandler("git", git_command))
    app.add_handler(CommandHandler("pak", pak_command))

    # एडमिन कमांड्स
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("dm", dm_command))
    app.add_handler(CommandHandler("bulkdm", bulkdm_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("deleteuser", deleteuser_command))
    app.add_handler(CommandHandler("searchuser", searchuser_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("recentusers", recentusers_command))
    app.add_handler(CommandHandler("userlookups", userlookups_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("inactiveusers", inactiveusers_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("dailystats", dailystats_command))
    app.add_handler(CommandHandler("lookupstats", lookupstats_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("topref", topref_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command))
    app.add_handler(CommandHandler("listadmins", listadmins_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("fulldbbackup", fulldbbackup_command))

    # कॉलबैक हैंडलर
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("बॉट पोलिंग शुरू...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
