import os
import json
import logging
import re
import random
import string
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from database import (
    init_db, add_user, update_user, get_user, add_credits, deduct_credit, has_credits, set_credits,
    ban_user, unban_user, is_banned, is_admin, set_admin,
    get_all_users, get_users_page, search_users, get_recent_users, get_user_lookups,
    get_leaderboard, get_premium_users, get_low_credit_users, get_inactive_users,
    add_referral, get_referral_count,
    create_code, get_code, redeem_code, list_codes, deactivate_code, get_code_stats,
    check_expired_codes, clean_expired_codes,
    log_lookup, get_lookup_stats,
    is_premium_for_all, set_premium_for_all, is_free_credits_on_join, set_free_credits_on_join,
    get_setting, set_setting
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DEFAULT_CREDITS = int(os.getenv("DEFAULT_CREDITS", 5))
REFERRAL_CREDIT = int(os.getenv("REFERRAL_CREDIT", 3))

# Force channels
FORCE_CHANNELS = []
if os.getenv("FORCE_CHANNEL1_ID"):
    FORCE_CHANNELS.append({
        "id": int(os.getenv("FORCE_CHANNEL1_ID")),
        "link": os.getenv("FORCE_CHANNEL1_LINK")
    })
if os.getenv("FORCE_CHANNEL2_ID"):
    FORCE_CHANNELS.append({
        "id": int(os.getenv("FORCE_CHANNEL2_ID")),
        "link": os.getenv("FORCE_CHANNEL2_LINK")
    })

# Log channels mapping
LOG_CHANNELS = {
    "num": os.getenv("LOG_CHANNEL_NUM"),
    "ifsc": os.getenv("LOG_CHANNEL_IFSC"),
    "email": os.getenv("LOG_CHANNEL_EMAIL"),
    "gst": os.getenv("LOG_CHANNEL_GST"),
    "vehicle": os.getenv("LOG_CHANNEL_VEHICLE"),
    "chalan": os.getenv("LOG_CHANNEL_CHALAN"),
    "pincode": os.getenv("LOG_CHANNEL_PINCODE"),
    "instagram": os.getenv("LOG_CHANNEL_INSTAGRAM"),
    "github": os.getenv("LOG_CHANNEL_GITHUB"),
    "pakistan": os.getenv("LOG_CHANNEL_PAKISTAN"),
    "ip": os.getenv("LOG_CHANNEL_IP"),
    "ffinfo": os.getenv("LOG_CHANNEL_FF_INFO"),
    "ffban": os.getenv("LOG_CHANNEL_FF_BAN"),
    "tg2num": os.getenv("LOG_CHANNEL_TG2NUM"),
    "tginfo": os.getenv("LOG_CHANNEL_TG_TO_INFO"),
    "tginfopro": os.getenv("LOG_CHANNEL_TGPRO"),
}

# API endpoints
API_URLS = {
    "num": os.getenv("API_NUM"),
    "tg2num": os.getenv("API_TG2NUM"),
    "vehicle": os.getenv("API_VEHICLE"),
    "chalan": os.getenv("API_VEHICLE_CHALAN"),
    "ip": os.getenv("API_IP"),
    "email": os.getenv("API_EMAIL"),
    "ffinfo": os.getenv("API_FF_INFO"),
    "ffban": os.getenv("API_FF_BAN"),
    "pincode": os.getenv("API_PINCODE"),
    "ifsc": os.getenv("API_IFSC"),
    "gst": os.getenv("API_GST"),
    "instagram": os.getenv("API_INSTAGRAM"),
    "tginfo": os.getenv("API_TG_INFO"),
    "tginfopro": os.getenv("API_TG_INFO_PRO"),
    "github": os.getenv("API_GITHUB"),
    "pakistan": os.getenv("API_PAKISTAN_NUMBER"),
}

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Branding
BRANDING = "\n\n---\n👨‍💻 developer: @Nullprotocol_X\n⚡ powered_by: NULL PROTOCOL"

# ---------- ब्रांडिंग हटाने वाला फंक्शन (सिर्फ num के लिए) ----------
UNWANTED_BRANDS = {
    '@patelkrish_99', 'patelkrish_99', 't.me/anshapi', 'anshapi', 'validity'
    '"@Kon_Hu_Mai"', 'Kon_Hu_Mai', '@kon_hu_mai', 'hours_remaining', 'days_remaining', 'April 6, 2026', 'expires_on', 'channel',
    'Dm to buy access', '"Dm to buy access"', 'dm to buy', 'owner', 'credit', 'code', '@AbdulDevStoreBot', 'AbdulDevStoreBot', 'https://t.me/AbdulBotzOfficial'
}

def clean_json_data(data, command_name):
    """अगर कमांड 'num' है तो JSON से अनचाही ब्रांडिंग हटाएँ"""
    if command_name != "num":
        return data

    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            # value को साफ करें
            if isinstance(value, str):
                for brand in UNWANTED_BRANDS:
                    value = value.replace(brand, '').strip()
                if value == '':
                    continue  # पूरी तरह खाली हो तो हटा दें
            elif isinstance(value, (dict, list)):
                value = clean_json_data(value, command_name)
            cleaned[key] = value
        return cleaned

    elif isinstance(data, list):
        cleaned = []
        for item in data:
            cleaned_item = clean_json_data(item, command_name)
            # अगर item डिक्शनरी है और खाली हो गई तो मत जोड़ो
            if isinstance(cleaned_item, dict) and not cleaned_item:
                continue
            if isinstance(cleaned_item, str) and cleaned_item == '':
                continue
            cleaned.append(cleaned_item)
        return cleaned

    elif isinstance(data, str):
        for brand in UNWANTED_BRANDS:
            data = data.replace(brand, '').strip()
        return data

    return data

# ---------- Helper Functions ----------
async def is_user_in_channel(user_id: int, channel_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status not in [ChatMember.LEFT, ChatMember.BANNED]
    except Exception as e:
        logger.error(f"Channel check error: {e}")
        return False

async def force_channel_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    # Admin exempt
    if is_admin(user_id):
        return True
    not_joined = []
    for ch in FORCE_CHANNELS:
        if not await is_user_in_channel(user_id, ch["id"], context):
            not_joined.append(ch)
    if not_joined:
        text = "⚠️ Bot use karne ke liye aapko ye channels join karne honge:\n\n"
        keyboard = []
        for ch in not_joined:
            text += f"• {ch['link']}\n"
            keyboard.append([InlineKeyboardButton(f"🔗 Join karein", url=ch["link"])])
        keyboard.append([InlineKeyboardButton("🔄 Check again", callback_data="check_again")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
        return False
    return True

async def fetch_api(url: str) -> dict | None:
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API error: {e}")
        return None

async def send_json_response(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             json_data: dict, input_value: str, command_name: str):
    # पहले JSON को साफ करें (सिर्फ num के लिए)
    cleaned_data = clean_json_data(json_data, command_name)

    formatted = json.dumps(cleaned_data, indent=2, ensure_ascii=False)
    if len(formatted) > 3800:
        formatted = formatted[:3800] + "\n... (truncated)"
    text = f"```json\n{formatted}\n```{BRANDING}"
    keyboard = [[
        InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{command_name}:{input_value}"),
        InlineKeyboardButton("📋 Copy JSON", callback_data=f"copy:{command_name}:{input_value}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=reply_markup)

    # Log to database
    log_lookup(update.effective_user.id, command_name, input_value, success=True)

    # Log to channel
    log_channel = LOG_CHANNELS.get(command_name)
    if log_channel:
        user = update.effective_user
        log_text = (
            f"🆔 User ID: {user.id}\n"
            f"👤 Username: @{user.username if user.username else 'None'}\n"
            f"📛 Name: {user.first_name}\n"
            f"🔹 Command: /{command_name}\n"
            f"📥 Input: `{input_value}`\n"
            f"📦 Response:\n```json\n{formatted}\n```"
        )
        try:
            await context.bot.send_message(chat_id=int(log_channel), text=log_text, parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Log channel error: {e}")

async def check_credits_and_deduct(user_id, command, input_val, update, context):
    if not has_credits(user_id):
        await update.message.reply_text(
            "❌ Aapke paas enough credits nahi hain.\n"
            "Credits pane ke liye /refer use karein ya /buy se kharidein."
        )
        return False
    deduct_credit(user_id)
    return True

async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if is_premium_for_all():
        return
    await update.message.reply_text(
        "❌ Ye bot sirf group mein kaam karta hai.\n\n"
        "Agar aap personally info lena chahte hain to ye bot use karein: @osintfatherNProbot"
    )
    return

# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)

    # Check for referral
    if context.args and context.args[0].startswith("ref_"):
        referrer_id = int(context.args[0].split("_")[1])
        if referrer_id != user.id:
            if add_referral(referrer_id, user.id):
                add_credits(referrer_id, REFERRAL_CREDIT)
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 Aapke referral se ek naya user join hua! Aapko {REFERRAL_CREDIT} credits mile."
                )

    if is_free_credits_on_join():
        user_data = get_user(user.id)
        if user_data and user_data['credits'] == 0:
            add_credits(user.id, DEFAULT_CREDITS)

    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return

    if not await force_channel_check(update, context):
        return

    user_data = get_user(user.id)
    await update.message.reply_text(
        f"Namaste {user.first_name}! 🙌\n"
        f"Main ek multi-purpose OSINT bot hoon.\n"
        f"Commands ki list ke liye /help karein.\n"
        f"Aapke paas {user_data['credits']} credits hain."
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return
    if not await force_channel_check(update, context):
        return
    text = (
        "🤖 *Available commands:*\n"
        "/num <10 digit number> – Mobile number info\n"
        "/tg2num <telegram id> – Telegram ID se number\n"
        "/vehicle <vehicle number> – Vehicle owner info\n"
        "/chalan <vehicle number> – Challan info\n"
        "/ip <ip address> – IP location\n"
        "/email <email> – Email info\n"
        "/ffinfo <free fire uid> – Free Fire profile\n"
        "/ffban <free fire uid> – Free Fire ban status\n"
        "/pincode <pincode> – Pincode details\n"
        "/ifsc <ifsc code> – Bank IFSC info\n"
        "/gst <gst number> – GST info\n"
        "/instagram <username> – Instagram info\n"
        "/tginfo <@username> – Telegram user info\n"
        "/tginfopro <telegram id> – Telegram pro info\n"
        "/github <username> – GitHub profile\n"
        "/pakistan <pakistan number> – Pakistan number info\n\n"
        "📱 *User commands:*\n"
        "/myprofile – Apna profile dekhein\n"
        "/refer – Referral link aur info\n"
        "/redeem <code> – Redeem code use karein\n"
        "/buy – Credits kharidne ki info"
    )
    if is_admin(user.id):
        text += "\n\n🛠 *Admin commands:*\n" + (
            "/stats – Bot stats\n"
            "/broadcast – Sabhi users ko message bhejein\n"
            "/dm – Kisi user ko direct message\n"
            "/gift – Credits gift karein\n"
            "/bulkgift – Bulk gift\n"
            "/removecredits – Credits hatayein\n"
            "/resetcredits – Credits reset\n"
            "/ban – User ban karein\n"
            "/unban – Unban karein\n"
            "/deleteuser – User delete karein\n"
            "/searchuser – User dhundhein\n"
            "/users – User list\n"
            "/recentusers – Recent users\n"
            "/userlookups – User lookup history\n"
            "/leaderboard – Top credits\n"
            "/premiumusers – Premium users (100+ credits)\n"
            "/lowcreditusers – Low credit users\n"
            "/inactiveusers – Inactive users\n"
            "/gencode – Random code generate\n"
            "/customcode – Custom code\n"
            "/listcodes – Saare codes\n"
            "/activecodes – Active codes\n"
            "/inactivecodes – Inactive codes\n"
            "/deactivatecode – Code deactivate\n"
            "/codestats – Code stats\n"
            "/checkexpired – Expired codes check\n"
            "/cleanexpired – Expired codes hatayein\n"
            "/dailystats – Daily stats\n"
            "/lookupstats – Lookup stats\n"
            "/backup – Data backup\n"
            "/topref – Top referrers"
        )
    if user.id == OWNER_ID:
        text += "\n\n👑 *Owner commands:*\n" + (
            "/addadmin – Admin jodein\n"
            "/removeadmin – Admin hatayein\n"
            "/listadmins – Admin list\n"
            "/settings – Bot settings\n"
            "/fulldbbackup – Full database backup\n"
            "/premiumforallusers – Sabke liye premium mode on\n"
            "/freemiumforallusers – Premium mode off"
        )
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- API Command Factory ----------
def create_api_handler(cmd_name):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if update.effective_chat.type == "private" and not is_premium_for_all():
            await private_message_handler(update, context)
            return
        if not await force_channel_check(update, context):
            return
        if is_banned(user.id):
            await update.message.reply_text("❌ Aap is bot se banned hain.")
            return
        args = context.args
        if not args:
            await update.message.reply_text(f"❌ Input dein. Example: /{cmd_name} <value>")
            return
        input_val = " ".join(args).strip()
        if not await check_credits_and_deduct(user.id, cmd_name, input_val, update, context):
            return
        url = API_URLS.get(cmd_name) + input_val
        data = await fetch_api(url)
        if data:
            await send_json_response(update, context, data, input_val, cmd_name)
        else:
            await update.message.reply_text("❌ API se data nahi mil paya.")
    return handler

# ---------- User Commands ----------
async def myprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return
    if not await force_channel_check(update, context):
        return
    user_data = get_user(user.id)
    if not user_data:
        await update.message.reply_text("❌ User nahi mila.")
        return
    joined = datetime.fromisoformat(user_data['joined_date']).strftime("%d-%m-%Y")
    text = (
        f"👤 *User Profile*\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"👤 Username: @{user.username if user.username else 'None'}\n"
        f"💰 Credits: {user_data['credits']}\n"
        f"📊 Total Earned: {user_data['total_earned']}\n"
        f"👥 Referrals: {user_data['referrals']}\n"
        f"🎫 Codes Claimed: {user_data['codes_claimed']}\n"
        f"📅 Joined: {joined}\n"
        f"🔗 Referral Link:\n"
        f"`https://t.me/{(await context.bot.get_me()).username}?start=ref_{user.id}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return
    if not await force_channel_check(update, context):
        return
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    text = (
        "🔗 *Refer & Earn Program*\n\n"
        "Apne dosto ko invite karein aur free credits paayein!\n"
        f"Per Referral: +{REFERRAL_CREDIT} Credits\n\n"
        "👇 *Your Link:*\n"
        f"`{ref_link}`\n\n"
        "📊 *How it works:*\n"
        "1. Apna link share karein\n"
        "2. Jo bhi is link se join karega\n"
        f"3. Aapko {REFERRAL_CREDIT} credits milenge"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return
    if not await force_channel_check(update, context):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Code dein. Example: /redeem ABC123")
        return
    code = args[0].strip().upper()
    success, result = redeem_code(user.id, code)
    if success:
        await update.message.reply_text(f"✅ Code successfully redeem ho gaya! Aapko {result} credits mile.")
    else:
        await update.message.reply_text(f"❌ Redeem fail: {result}")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and not is_premium_for_all():
        await private_message_handler(update, context)
        return
    if not await force_channel_check(update, context):
        return
    await update.message.reply_text(
        "💳 *Credits kharidne ke liye*\n\n"
        "Owner se contact karein: @Nullprotocol_X\n"
        "Ya Telegram par message bhejein."
    )

# ---------- Admin Commands ----------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    users = get_all_users()
    total_users = len(users)
    banned = sum(1 for u in users if u['banned'])
    admins = sum(1 for u in users if u['is_admin'] or u['user_id'] == OWNER_ID)
    total_credits = sum(u['credits'] for u in users)
    total_lookups, successful_lookups = get_lookup_stats()
    text = (
        f"📊 *Bot Stats*\n"
        f"Total users: {total_users}\n"
        f"Banned: {banned}\n"
        f"Admins: {admins}\n"
        f"Total credits: {total_credits}\n"
        f"Total lookups: {total_lookups}\n"
        f"Successful lookups: {successful_lookups}\n"
        f"Owner ID: {OWNER_ID}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    if not context.args:
        await update.message.reply_text("❌ Message dein.")
        return
    message = " ".join(context.args)
    users = get_all_users()
    success = 0
    fail = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u['user_id'], text=message)
            success += 1
        except:
            fail += 1
    await update.message.reply_text(f"✅ Broadcast complete!\nSuccess: {success}\nFailed: {fail}")

async def dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Use: /dm user_id message")
        return
    target_id = int(args[0])
    msg = " ".join(args[1:])
    try:
        await context.bot.send_message(chat_id=target_id, text=msg)
        await update.message.reply_text(f"✅ Message bhej diya gaya.")
    except Exception as e:
        await update.message.reply_text(f"❌ Fail: {e}")

async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Use: /gift user_id amount")
        return
    target_id = int(args[0])
    amount = int(args[1])
    add_credits(target_id, amount)
    await update.message.reply_text(f"✅ {target_id} ko {amount} credits de diye.")

async def bulkgift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Use: /bulkgift amount id1 id2 ...")
        return
    amount = int(args[0])
    ids = [int(x) for x in args[1:]]
    for uid in ids:
        add_credits(uid, amount)
    await update.message.reply_text(f"✅ {len(ids)} users ko {amount} credits de diye.")

async def removecredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Use: /removecredits user_id amount")
        return
    target_id = int(args[0])
    amount = int(args[1])
    user_data = get_user(target_id)
    if user_data:
        new_credits = max(0, user_data['credits'] - amount)
        set_credits(target_id, new_credits)
        await update.message.reply_text(f"✅ {target_id} se {amount} credits hataye gaye. Ab {new_credits} credits.")
    else:
        await update.message.reply_text("❌ User nahi mila.")

async def resetcredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /resetcredits user_id")
        return
    target_id = int(args[0])
    set_credits(target_id, 0)
    await update.message.reply_text(f"✅ {target_id} ke credits reset kar diye.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /ban user_id")
        return
    target_id = int(args[0])
    if target_id == OWNER_ID:
        await update.message.reply_text("❌ Owner ko ban nahi kar sakte.")
        return
    ban_user(target_id)
    await update.message.reply_text(f"✅ {target_id} ban kar diya gaya.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /unban user_id")
        return
    target_id = int(args[0])
    unban_user(target_id)
    await update.message.reply_text(f"✅ {target_id} unban kar diya gaya.")

async def deleteuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /deleteuser user_id")
        return
    target_id = int(args[0])
    set_credits(target_id, 0)
    ban_user(target_id)
    await update.message.reply_text(f"✅ {target_id} delete kar diya gaya (ban + credits 0).")

async def searchuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /searchuser query")
        return
    query = " ".join(args)
    results = search_users(query)
    if not results:
        await update.message.reply_text("❌ Koi user nahi mila.")
        return
    text = "🔍 *Search results:*\n"
    for u in results[:10]:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'} | Credits: {u['credits']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except:
            pass
    users_list, total = get_users_page(page)
    if not users_list:
        await update.message.reply_text("❌ Koi user nahi.")
        return
    text = f"📋 *User list (page {page})*\n"
    for u in users_list:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'} | Credits: {u['credits']}\n"
    text += f"\nTotal users: {total}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def recentusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
        except:
            pass
    recent = get_recent_users(days)
    text = f"📅 *Pichle {days} dinon mein naye users:* {len(recent)}\n"
    for u in recent[:20]:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'} | {u['joined_date']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def userlookups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /userlookups user_id")
        return
    target_id = int(args[0])
    lookups = get_user_lookups(target_id)
    if not lookups:
        await update.message.reply_text("❌ Koi lookup nahi.")
        return
    text = f"🔍 *{target_id} ke lookups:*\n"
    for l in lookups[:20]:
        text += f"• /{l['command']} {l['input']} | {l['timestamp']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except:
            pass
    top = get_leaderboard(limit)
    text = "🏆 *Credits Leaderboard*\n"
    for i, u in enumerate(top, 1):
        text += f"{i}. `{u['user_id']}` | @{u['username'] or 'None'} | {u['credits']} credits\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def premiumusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    premium = get_premium_users(100)
    text = f"💰 *Premium users (100+ credits)*: {len(premium)}\n"
    for u in premium[:20]:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'} | {u['credits']} credits\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def lowcreditusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    low = get_low_credit_users(10)
    text = f"📉 *Low credit users (10 se kam)*: {len(low)}\n"
    for u in low[:20]:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'} | {u['credits']} credits\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def inactiveusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except:
            pass
    inactive = get_inactive_users(days)
    text = f"⏰ *{days} din se inactive users*: {len(inactive)}\n"
    for u in inactive[:20]:
        text += f"• `{u['user_id']}` | @{u['username'] or 'None'}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- Code Management ----------
async def gencode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("❌ Use: /gencode amount max_uses [time]")
        return
    amount = int(args[0])
    max_uses = int(args[1])
    expiry = None
    if len(args) >= 3:
        time_str = args[2]
        match = re.match(r'(\d+)([mhd])', time_str)
        if match:
            val, unit = int(match.group(1)), match.group(2)
            if unit == 'm':
                delta = timedelta(minutes=val)
            elif unit == 'h':
                delta = timedelta(hours=val)
            elif unit == 'd':
                delta = timedelta(days=val)
            expiry = (datetime.now() + delta).isoformat()
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    create_code(code, amount, max_uses, expiry, user.id)
    await update.message.reply_text(f"✅ Code generate hua: `{code}`\nAmount: {amount}\nMax uses: {max_uses}\nExpiry: {expiry or 'Never'}", parse_mode="Markdown")

async def customcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Use: /customcode code amount max_uses [time]")
        return
    code = args[0].upper()
    amount = int(args[1])
    max_uses = int(args[2])
    expiry = None
    if len(args) >= 4:
        time_str = args[3]
        match = re.match(r'(\d+)([mhd])', time_str)
        if match:
            val, unit = int(match.group(1)), match.group(2)
            if unit == 'm':
                delta = timedelta(minutes=val)
            elif unit == 'h':
                delta = timedelta(hours=val)
            elif unit == 'd':
                delta = timedelta(days=val)
            expiry = (datetime.now() + delta).isoformat()
    try:
        create_code(code, amount, max_uses, expiry, user.id)
        await update.message.reply_text(f"✅ Custom code bana: `{code}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Code banane mein error: {e}")

async def listcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    codes = list_codes(active_only=False)
    if not codes:
        await update.message.reply_text("❌ Koi code nahi.")
        return
    text = "📋 *Saare codes:*\n"
    for c in codes[:20]:
        text += f"• `{c['code']}` | {c['amount']} credits | Uses: {c['uses']}/{c['max_uses']} | Active: {c['active']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def activecodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    codes = list_codes(active_only=True)
    if not codes:
        await update.message.reply_text("❌ Koi active code nahi.")
        return
    text = "✅ *Active codes:*\n"
    for c in codes[:20]:
        text += f"• `{c['code']}` | {c['amount']} credits | Uses: {c['uses']}/{c['max_uses']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def inactivecodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    codes = list_codes(active_only=False)
    inactive = [c for c in codes if not c['active']]
    if not inactive:
        await update.message.reply_text("❌ Koi inactive code nahi.")
        return
    text = "❌ *Inactive codes:*\n"
    for c in inactive[:20]:
        text += f"• `{c['code']}`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def deactivatecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /deactivatecode code")
        return
    code = args[0].upper()
    deactivate_code(code)
    await update.message.reply_text(f"✅ Code `{code}` deactivate kar diya gaya.", parse_mode="Markdown")

async def codestats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /codestats code")
        return
    code = args[0].upper()
    stats = get_code_stats(code)
    if not stats:
        await update.message.reply_text("❌ Code nahi mila.")
        return
    text = (
        f"📊 *Code stats: {code}*\n"
        f"Amount: {stats['amount']}\n"
        f"Total Uses: {stats['total_uses']}\n"
        f"Max Uses: {stats['max_uses']}\n"
        f"Expiry: {stats['expiry'] or 'Never'}\n"
        f"Active: {'✅' if stats['active'] else '❌'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def checkexpired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    expired = check_expired_codes()
    if not expired:
        await update.message.reply_text("✅ Koi expired code nahi.")
    else:
        await update.message.reply_text(f"⚠️ Expired codes: {', '.join(expired)}")

async def cleanexpired(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    clean_expired_codes()
    await update.message.reply_text("✅ Saare expired codes inactive kar diye gaye.")

# ---------- Statistics ----------
async def dailystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
        except:
            pass
    await update.message.reply_text(f"📅 Pichle {days} dinon ke stats jald hi available honge.")

async def lookupstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    total, success = get_lookup_stats()
    await update.message.reply_text(f"📊 Lookup stats:\nTotal: {total}\nSuccessful: {success}")

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except:
            pass
    await update.message.reply_text("✅ Backup feature jald hi aayega.")

async def topref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except:
            pass
    users = get_all_users()
    top = sorted(users, key=lambda x: x['referrals'], reverse=True)[:limit]
    text = "🏆 *Top Referrers*\n"
    for i, u in enumerate(top, 1):
        text += f"{i}. `{u['user_id']}` | @{u['username'] or 'None'} | {u['referrals']} referrals\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- Owner Commands ----------
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /addadmin user_id")
        return
    target_id = int(args[0])
    set_admin(target_id, 1)
    await update.message.reply_text(f"✅ {target_id} ko admin bana diya gaya.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Use: /removeadmin user_id")
        return
    target_id = int(args[0])
    if target_id == OWNER_ID:
        await update.message.reply_text("❌ Owner ko admin se nahi hataya ja sakta.")
        return
    set_admin(target_id, 0)
    await update.message.reply_text(f"✅ {target_id} se admin rights hata diye.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    users = get_all_users()
    admins = [u for u in users if u['is_admin'] or u['user_id'] == OWNER_ID]
    text = "👥 *Admin list*\n"
    for a in admins:
        text += f"• `{a['user_id']}` | @{a['username'] or 'None'}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    premium = is_premium_for_all()
    free = is_free_credits_on_join()
    text = (
        "⚙️ *Bot Settings*\n"
        f"Premium for all: {'✅' if premium else '❌'}\n"
        f"Free credits on join: {'✅' if free else '❌'}\n\n"
        "Badalne ke liye /premiumforallusers ya /freemiumforallusers use karein."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def fulldbbackup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    try:
        with open('bot.db', 'rb') as f:
            await context.bot.send_document(chat_id=user.id, document=f, filename='bot.db')
        import csv
        import io
        users = get_all_users()
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['user_id','username','first_name','credits','total_earned','referrals','codes_claimed','joined_date','banned','is_admin'])
        writer.writeheader()
        writer.writerows(users)
        await context.bot.send_document(chat_id=user.id, document=io.BytesIO(output.getvalue().encode()), filename='users.csv')
    except Exception as e:
        await update.message.reply_text(f"❌ Backup fail: {e}")

async def premiumforallusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    set_premium_for_all(True)
    users = get_all_users()
    for u in users:
        add_credits(u['user_id'], DEFAULT_CREDITS)
    await update.message.reply_text(f"✅ Premium for all mode on. Sabhi users ko {DEFAULT_CREDITS} credits de diye.")

async def freemiumforallusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return
    set_premium_for_all(False)
    await update.message.reply_text("✅ Premium for all mode off. Ab bot sirf group mein kaam karega.")

# ---------- Callback Handler ----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    action = data[0]
    if action == "check_again":
        user_id = update.effective_user.id
        not_joined = []
        for ch in FORCE_CHANNELS:
            if not await is_user_in_channel(user_id, ch["id"], context):
                not_joined.append(ch)
        if not_joined:
            await query.edit_message_text("❌ Aap abhi bhi saare channels mein nahi hain. Pehle join karein phir check again dabayein.")
        else:
            await query.edit_message_text("✅ Ab aap saare channels mein hain! Apna command dobara bhejein.")
        return
    if len(data) < 3:
        return
    command, input_val = data[1], ":".join(data[2:])
    url_template = API_URLS.get(command)
    if not url_template:
        await query.edit_message_text("Command nahi mila.")
        return
    full_url = url_template + input_val
    if action == "refresh":
        json_data = await fetch_api(full_url)
        if json_data:
            # Refresh mein bhi branding hatayenge
            cleaned_data = clean_json_data(json_data, command)
            formatted = json.dumps(cleaned_data, indent=2, ensure_ascii=False)
            if len(formatted) > 3800:
                formatted = formatted[:3800] + "\n... (truncated)"
            text = f"```json\n{formatted}\n```{BRANDING}"
            keyboard = [[
                InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{command}:{input_val}"),
                InlineKeyboardButton("📋 Copy JSON", callback_data=f"copy:{command}:{input_val}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="MarkdownV2", reply_markup=reply_markup)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ API se data nahi mil paya.")
    elif action == "copy":
        json_data = await fetch_api(full_url)
        if json_data:
            cleaned_data = clean_json_data(json_data, command)
            formatted = json.dumps(cleaned_data, indent=2, ensure_ascii=False)
            if len(formatted) > 3800:
                formatted = formatted[:3800] + "\n... (truncated)"
            text = f"```json\n{formatted}\n```"
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="MarkdownV2")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ API se data nahi mil paya.")

# ---------- Main ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # API commands
    for cmd in API_URLS:
        if API_URLS[cmd]:
            app.add_handler(CommandHandler(cmd, create_api_handler(cmd)))

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("myprofile", myprofile))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("buy", buy))

    # Admin commands
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("dm", dm))
    app.add_handler(CommandHandler("gift", gift))
    app.add_handler(CommandHandler("bulkgift", bulkgift))
    app.add_handler(CommandHandler("removecredits", removecredits))
    app.add_handler(CommandHandler("resetcredits", resetcredits))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("deleteuser", deleteuser))
    app.add_handler(CommandHandler("searchuser", searchuser))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("recentusers", recentusers))
    app.add_handler(CommandHandler("userlookups", userlookups))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("premiumusers", premiumusers))
    app.add_handler(CommandHandler("lowcreditusers", lowcreditusers))
    app.add_handler(CommandHandler("inactiveusers", inactiveusers))
    app.add_handler(CommandHandler("gencode", gencode))
    app.add_handler(CommandHandler("customcode", customcode))
    app.add_handler(CommandHandler("listcodes", listcodes))
    app.add_handler(CommandHandler("activecodes", activecodes))
    app.add_handler(CommandHandler("inactivecodes", inactivecodes))
    app.add_handler(CommandHandler("deactivatecode", deactivatecode))
    app.add_handler(CommandHandler("codestats", codestats))
    app.add_handler(CommandHandler("checkexpired", checkexpired))
    app.add_handler(CommandHandler("cleanexpired", cleanexpired))
    app.add_handler(CommandHandler("dailystats", dailystats))
    app.add_handler(CommandHandler("lookupstats", lookupstats))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("topref", topref))

    # Owner commands
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("listadmins", listadmins))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("fulldbbackup", fulldbbackup))
    app.add_handler(CommandHandler("premiumforallusers", premiumforallusers))
    app.add_handler(CommandHandler("freemiumforallusers", freemiumforallusers))

    # Callback handler
    app.add_handler(CallbackQueryHandler(button_callback))

    # Private message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, private_message_handler))

    logger.info("Bot shuru ho raha hai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
