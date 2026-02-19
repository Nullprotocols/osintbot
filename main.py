import os
import sys
import json
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from typing import List, Optional, Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
import aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import aiosqlite
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
OWNER_ID = 8104850843
ADMIN_IDS = [8104850843, 5987905091]
FORCE_JOIN_CHANNELS = [
    {"username": "all_data_here", "id": -1003090922367},
    {"username": "osint_lookup", "id": -1003698567122}
]
LOG_CHANNELS = {
    "num": -1003482423742,
    "ifsc": -1003624886596,
    "email": -1003431549612,
    "gst": -1003634866992,
    "vehicle": -1003237155636,
    "pincode": -1003677285823,
    "instagram": -1003498414978,
    "github": -1003576017442,
    "pakistan": -1003663672738,
    "ip": -1003665811220,
    "ff_info": -1003588577282,
    "ff_ban": -1003521974255,
    "tg2num": -1003642820243,
    "chalan": -1003237155636,
    "tg_to_info": -1003643170105,
    "tgpro": -1003643170105,
    "adr": -1003482423742,
}
BRANDING_BLOCKLIST = [
    "@patelkrish_99", "patelkrish_99", "t.me/anshapi", "anshapi", "@Kon_Hu_Mai", "Dm to buy access", "Kon_Hu_Mai"
]
EXTRA_NUMBER_BLOCK = [
    "dm to buy", "owner", "@kon_hu_mai", "Ruk ja bhencho itne m kya unlimited request lega?? Paid lena h to bolo 100-400₹ @Simpleguy444"
]
API_ENDPOINTS = {
    "num": "https://num-free-rootx-jai-shree-ram-14-day.vercel.app/?key=lundkinger&number={}",
    "tg2num": "https://tg2num-owner-api.vercel.app/?userid={}",
    "vehicle": "https://vehicle-info-aco-api.vercel.app/info?vehicle={}",
    "vchalan": "https://api.b77bf911.workers.dev/vehicle?registration={}",
    "ip": "https://abbas-apis.vercel.app/api/ip?ip={}",
    "email": "https://abbas-apis.vercel.app/api/email?mail={}",
    "ffinfo": "https://official-free-fire-info.onrender.com/player-info?key=DV_M7-INFO_API&uid={}",
    "ffban": "https://abbas-apis.vercel.app/api/ff-ban?uid={}",
    "pin": "https://api.postalpincode.in/pincode/{}",
    "ifsc": "https://abbas-apis.vercel.app/api/ifsc?ifsc={}",
    "gst": "https://api.b77bf911.workers.dev/gst?number={}",
    "insta": "https://mkhossain.alwaysdata.net/instanum.php?username={}",
    "tginfo": "https://openosintx.vippanel.in/tgusrinfo.php?key=OpenOSINTX-FREE&user={}",
    "tginfopro": "https://api.b77bf911.workers.dev/telegram?user={}",
    "git": "https://abbas-apis.vercel.app/api/github?username={}",
    "pak": "https://abbas-apis.vercel.app/api/pakistan?number={}",
    "adr": "https://api-ij32.onrender.com/aadhar?match={}",
}

# Initialize bot and dispatcher
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set in environment")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# Database import
from database import Database

# Global database instance
db = None

# Self-ping task handle
self_ping_task = None

# -------------------------------------------------------------------
# Utility functions
# -------------------------------------------------------------------

def clean_branding(text: str, command: str = None) -> str:
    """Remove banned phrases from text."""
    if not text:
        return text
    blocklist = BRANDING_BLOCKLIST.copy()
    if command == "num":
        blocklist.extend(EXTRA_NUMBER_BLOCK)
    for phrase in blocklist:
        text = text.replace(phrase, "")
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def fetch_api(url: str, retries: int = 3) -> Optional[Any]:
    """Fetch API with retry and backoff."""
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"API returned {resp.status} for {url}")
                        return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt+1} for {url}")
        except aiohttp.ClientError as e:
            logger.warning(f"Client error on attempt {attempt+1}: {e}")
        if attempt < retries - 1:
            await asyncio.sleep(2 ** attempt)
    return None

def format_result(data: Any, command: str) -> str:
    """Format API result as preformatted JSON with footer."""
    if data is None:
        text = "No data or error."
    else:
        try:
            text = json.dumps(data, indent=2, ensure_ascii=False)
        except:
            text = str(data)
    footer = "\n\ndeveloper: @Nullprotocol_X\npowered_by: NULL PROTOCOL"
    return f"<pre>{text}</pre>{footer}"

def get_result_keyboard() -> InlineKeyboardMarkup:
    """Inline buttons for copy and search."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Copy", callback_data="copy"),
        InlineKeyboardButton(text="Search", switch_inline_query="")
    )
    return builder.as_markup()

async def check_force_join(user_id: int) -> bool:
    """Check if user joined both required channels. Admins bypass."""
    # Check if admin
    cursor = await db.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    if await cursor.fetchone():
        return True
    for channel in FORCE_JOIN_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                return False
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning(f"Force join check failed for {user_id} in {channel['id']}: {e}")
            return False
    return True

async def send_force_join_prompt(message: Message):
    """Send force join message with buttons."""
    builder = InlineKeyboardBuilder()
    for ch in FORCE_JOIN_CHANNELS:
        builder.row(InlineKeyboardButton(text=f"Join {ch['username']}", url=f"https://t.me/{ch['username']}"))
    builder.row(InlineKeyboardButton(text="✅ Done", callback_data="check_join"))
    await message.reply(
        "Please join both channels to use the bot:",
        reply_markup=builder.as_markup()
    )

async def log_lookup(command: str, user_id: int, query: str, result: Any):
    """Send log to appropriate Telegram channel."""
    log_channel = LOG_CHANNELS.get(command)
    if not log_channel:
        return
    try:
        log_text = f"User: {user_id}\nQuery: {query}\nResult: {json.dumps(result, indent=2, ensure_ascii=False)}"
        if len(log_text) > 4000:
            log_text = log_text[:4000] + "..."
        await bot.send_message(log_channel, log_text)
    except Exception as e:
        logger.error(f"Failed to log lookup: {e}")

async def ensure_user_in_db(user_id: int, username: str = None, first_name: str = None):
    """Insert or update user in database."""
    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, first_seen, last_seen, total_lookups) VALUES (?, ?, ?, ?, ?, 0)",
        (user_id, username, first_name, now, now)
    )
    await db.execute(
        "UPDATE users SET last_seen = ?, username = ?, first_name = ? WHERE user_id = ?",
        (now, username, first_name, user_id)
    )
    await db.commit()

async def increment_lookups(user_id: int):
    await db.execute(
        "UPDATE users SET total_lookups = total_lookups + 1 WHERE user_id = ?",
        (user_id,)
    )
    await db.commit()

async def update_daily_stats(command: str):
    today = date.today().isoformat()
    await db.execute(
        "INSERT INTO daily_stats (date, command, count) VALUES (?, ?, 1) ON CONFLICT(date, command) DO UPDATE SET count = count + 1",
        (today, command)
    )
    await db.commit()

async def log_lookup_to_db(user_id: int, command: str, query: str):
    """Store lookup in database (for stats and history)."""
    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO lookups (user_id, command, query, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, command, query, now)
    )
    await db.commit()

# -------------------------------------------------------------------
# Permission checks
# -------------------------------------------------------------------

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

async def is_admin(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    cursor = await db.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    return await cursor.fetchone() is not None

async def is_banned(user_id: int) -> bool:
    cursor = await db.execute("SELECT user_id FROM banned WHERE user_id = ?", (user_id,))
    return await cursor.fetchone() is not None

async def check_group_and_join(message: Message) -> bool:
    """Verify that message is in group and user has joined channels."""
    if message.chat.type not in ["group", "supergroup"]:
        if await is_admin(message.from_user.id):
            return True
        await message.reply("Ye bot sirf group me kaam karta hai.\nPersonal use ke liye use kare: @osintfatherNullBot")
        return False
    if await is_banned(message.from_user.id):
        await message.reply("You are banned.")
        return False
    if not await is_admin(message.from_user.id):
        if not await check_force_join(message.from_user.id):
            await send_force_join_prompt(message)
            return False
    return True

# -------------------------------------------------------------------
# Command Handlers (OSINT commands)
# -------------------------------------------------------------------

async def handle_osint_command(message: Message, command: str, arg: str):
    """Generic handler for OSINT commands."""
    if not await check_group_and_join(message):
        return
    if not arg:
        await message.reply(f"Usage: /{command} <query>")
        return
    await ensure_user_in_db(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await increment_lookups(message.from_user.id)
    await update_daily_stats(command)
    await log_lookup_to_db(message.from_user.id, command, arg)
    url = API_ENDPOINTS[command].format(arg)
    data = await fetch_api(url)
    cleaned_data = None
    if data:
        if isinstance(data, dict):
            cleaned_data = {k: clean_branding(str(v), command) if isinstance(v, str) else v for k, v in data.items()}
        elif isinstance(data, list):
            cleaned_data = [clean_branding(str(item), command) if isinstance(item, str) else item for item in data]
        else:
            cleaned_data = clean_branding(str(data), command)
    else:
        cleaned_data = {"error": "No response from API"}
    result_text = format_result(cleaned_data, command)
    await message.reply(result_text, reply_markup=get_result_keyboard(), parse_mode=ParseMode.HTML)
    await log_lookup(command, message.from_user.id, arg, cleaned_data)

# Register all OSINT commands
@dp.message(Command("num"))
async def cmd_num(message: Message, command: CommandObject):
    await handle_osint_command(message, "num", command.args)

@dp.message(Command("tg2num"))
async def cmd_tg2num(message: Message, command: CommandObject):
    await handle_osint_command(message, "tg2num", command.args)

@dp.message(Command("vehicle"))
async def cmd_vehicle(message: Message, command: CommandObject):
    await handle_osint_command(message, "vehicle", command.args)

@dp.message(Command("vchalan"))
async def cmd_vchalan(message: Message, command: CommandObject):
    await handle_osint_command(message, "vchalan", command.args)

@dp.message(Command("ip"))
async def cmd_ip(message: Message, command: CommandObject):
    await handle_osint_command(message, "ip", command.args)

@dp.message(Command("email"))
async def cmd_email(message: Message, command: CommandObject):
    await handle_osint_command(message, "email", command.args)

@dp.message(Command("ffinfo"))
async def cmd_ffinfo(message: Message, command: CommandObject):
    await handle_osint_command(message, "ffinfo", command.args)

@dp.message(Command("ffban"))
async def cmd_ffban(message: Message, command: CommandObject):
    await handle_osint_command(message, "ffban", command.args)

@dp.message(Command("pin"))
async def cmd_pin(message: Message, command: CommandObject):
    await handle_osint_command(message, "pin", command.args)

@dp.message(Command("ifsc"))
async def cmd_ifsc(message: Message, command: CommandObject):
    await handle_osint_command(message, "ifsc", command.args)

@dp.message(Command("gst"))
async def cmd_gst(message: Message, command: CommandObject):
    await handle_osint_command(message, "gst", command.args)

@dp.message(Command("insta"))
async def cmd_insta(message: Message, command: CommandObject):
    await handle_osint_command(message, "insta", command.args)

@dp.message(Command("tginfo"))
async def cmd_tginfo(message: Message, command: CommandObject):
    await handle_osint_command(message, "tginfo", command.args)

@dp.message(Command("tginfopro"))
async def cmd_tginfopro(message: Message, command: CommandObject):
    await handle_osint_command(message, "tginfopro", command.args)

@dp.message(Command("git"))
async def cmd_git(message: Message, command: CommandObject):
    await handle_osint_command(message, "git", command.args)

@dp.message(Command("pak"))
async def cmd_pak(message: Message, command: CommandObject):
    await handle_osint_command(message, "pak", command.args)

@dp.message(Command("adr"))
async def cmd_adr(message: Message, command: CommandObject):
    await handle_osint_command(message, "adr", command.args)

# -------------------------------------------------------------------
# Admin commands
# -------------------------------------------------------------------

async def admin_only(message: Message) -> bool:
    if not await is_admin(message.from_user.id):
        await message.reply("Unauthorized.")
        return False
    return True

@dp.message(Command("addadmin"))
async def cmd_addadmin(message: Message, command: CommandObject):
    if not is_owner(message.from_user.id):
        await message.reply("Owner only.")
        return
    if not command.args:
        await message.reply("Usage: /addadmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    await db.commit()
    await message.reply(f"Admin {user_id} added.")

@dp.message(Command("removeadmin"))
async def cmd_removeadmin(message: Message, command: CommandObject):
    if not is_owner(message.from_user.id):
        await message.reply("Owner only.")
        return
    if not command.args:
        await message.reply("Usage: /removeadmin <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    await db.commit()
    await message.reply(f"Admin {user_id} removed.")

@dp.message(Command("listadmins"))
async def cmd_listadmins(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT user_id FROM admins")
    rows = await cursor.fetchall()
    admin_list = "\n".join(str(r[0]) for r in rows)
    await message.reply(f"Admins:\n{admin_list}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    if not command.args:
        await message.reply("Usage: /ban <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    await db.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (user_id,))
    await db.commit()
    await message.reply(f"User {user_id} banned.")

@dp.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    if not command.args:
        await message.reply("Usage: /unban <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    await db.execute("DELETE FROM banned WHERE user_id = ?", (user_id,))
    await db.commit()
    await message.reply(f"User {user_id} unbanned.")

@dp.message(Command("deleteuser"))
async def cmd_deleteuser(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    if not command.args:
        await message.reply("Usage: /deleteuser <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    await db.commit()
    await message.reply(f"User {user_id} deleted from database.")

@dp.message(Command("searchuser"))
async def cmd_searchuser(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    if not command.args:
        await message.reply("Usage: /searchuser <user_id or username>")
        return
    query = command.args.strip()
    if query.isdigit():
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (int(query),))
        row = await cursor.fetchone()
    else:
        cursor = await db.execute("SELECT * FROM users WHERE username LIKE ?", (f"%{query}%",))
        row = await cursor.fetchone()
    if row:
        await message.reply(f"User: {row}")
    else:
        await message.reply("Not found.")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    count = (await cursor.fetchone())[0]
    await message.reply(f"Total users: {count}")

@dp.message(Command("recentusers"))
async def cmd_recentusers(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT user_id, last_seen FROM users ORDER BY last_seen DESC LIMIT 10")
    rows = await cursor.fetchall()
    text = "\n".join(f"{r[0]} - {r[1]}" for r in rows)
    await message.reply(f"Recent users:\n{text}")

@dp.message(Command("userlookups"))
async def cmd_userlookups(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    if not command.args:
        await message.reply("Usage: /userlookups <user_id>")
        return
    try:
        user_id = int(command.args.strip())
    except:
        await message.reply("Invalid user ID.")
        return
    cursor = await db.execute(
        "SELECT command, query, timestamp FROM lookups WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
        (user_id,)
    )
    rows = await cursor.fetchall()
    if not rows:
        await message.reply("No lookups.")
        return
    text = "\n".join(f"{r[2]}: /{r[0]} {r[1]}" for r in rows)
    await message.reply(text[:4000])

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT user_id, total_lookups FROM users ORDER BY total_lookups DESC LIMIT 10")
    rows = await cursor.fetchall()
    text = "\n".join(f"{r[0]} - {r[1]} lookups" for r in rows)
    await message.reply(f"Leaderboard:\n{text}")

@dp.message(Command("inactiveusers"))
async def cmd_inactiveusers(message: Message):
    if not await admin_only(message):
        return
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
    cursor = await db.execute("SELECT user_id FROM users WHERE last_seen < ?", (cutoff,))
    rows = await cursor.fetchall()
    count = len(rows)
    await message.reply(f"Inactive users (30 days): {count}")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    total_users = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM lookups")
    total_lookups = (await cursor.fetchone())[0]
    await message.reply(f"Total users: {total_users}\nTotal lookups: {total_lookups}")

@dp.message(Command("dailystats"))
async def cmd_dailystats(message: Message):
    if not await admin_only(message):
        return
    today = date.today().isoformat()
    cursor = await db.execute("SELECT command, count FROM daily_stats WHERE date = ?", (today,))
    rows = await cursor.fetchall()
    if not rows:
        await message.reply("No stats today.")
        return
    text = "\n".join(f"/{r[0]}: {r[1]}" for r in rows)
    await message.reply(f"Today's stats:\n{text}")

@dp.message(Command("lookupstats"))
async def cmd_lookupstats(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT command, COUNT(*) FROM lookups GROUP BY command ORDER BY COUNT(*) DESC")
    rows = await cursor.fetchall()
    text = "\n".join(f"/{r[0]}: {r[1]}" for r in rows)
    await message.reply(f"Lookup stats:\n{text}")

@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    if not is_owner(message.from_user.id):
        return
    await message.reply("Settings: not implemented.")

@dp.message(Command("fulldbbackup"))
async def cmd_fulldbbackup(message: Message):
    if not is_owner(message.from_user.id):
        return
    db_path = os.getenv("DATABASE_PATH", "bot_database.sqlite")
    try:
        with open(db_path, "rb") as f:
            await message.reply_document(f, caption="Database backup")
    except Exception as e:
        await message.reply(f"Backup failed: {e}")

# -------------------------------------------------------------------
# Broadcast and DM commands
# -------------------------------------------------------------------

async def broadcast_task(admin_msg: Message, users: List[int], media: Optional[types.Message] = None):
    """Send broadcast to list of users."""
    sent = 0
    failed = 0
    for uid in users:
        try:
            if media:
                if media.photo:
                    await bot.send_photo(uid, media.photo[-1].file_id, caption=media.caption)
                elif media.video:
                    await bot.send_video(uid, media.video.file_id, caption=media.caption)
                elif media.document:
                    await bot.send_document(uid, media.document.file_id, caption=media.caption)
                elif media.voice:
                    await bot.send_voice(uid, media.voice.file_id, caption=media.caption)
                elif media.text:
                    await bot.send_message(uid, media.text)
            else:
                await bot.send_message(uid, admin_msg.text.split(maxsplit=1)[1] if admin_msg.text else "Broadcast")
            sent += 1
        except Exception as e:
            failed += 1
        await asyncio.sleep(0.05)
    await admin_msg.reply(f"Broadcast finished. Sent: {sent}, Failed: {failed}")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not await admin_only(message):
        return
    cursor = await db.execute("SELECT user_id FROM users")
    rows = await cursor.fetchall()
    users = [r[0] for r in rows]
    if not users:
        await message.reply("No users.")
        return
    if message.reply_to_message:
        media_msg = message.reply_to_message
        asyncio.create_task(broadcast_task(message, users, media_msg))
        await message.reply(f"Broadcasting media to {len(users)} users...")
    else:
        if len(message.text.split()) < 2:
            await message.reply("Usage: /broadcast <text> or reply to media")
            return
        asyncio.create_task(broadcast_task(message, users))
        await message.reply(f"Broadcasting text to {len(users)} users...")

@dp.message(Command("dm"))
async def cmd_dm(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    args = command.args
    if not args:
        await message.reply("Usage: /dm user_id text")
        return
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /dm user_id text")
        return
    try:
        uid = int(parts[0])
    except:
        await message.reply("Invalid user ID.")
        return
    text = parts[1]
    try:
        await bot.send_message(uid, text)
        await message.reply(f"Message sent to {uid}.")
    except Exception as e:
        await message.reply(f"Failed: {e}")

@dp.message(Command("bulkdm"))
async def cmd_bulkdm(message: Message, command: CommandObject):
    if not await admin_only(message):
        return
    args = command.args
    if not args:
        await message.reply("Usage: /bulkdm id1 id2 ... text")
        return
    parts = args.split()
    if len(parts) < 2:
        await message.reply("Usage: /bulkdm id1 id2 ... text")
        return
    ids_text = parts[:-1]
    text = parts[-1]
    ids = []
    for p in ids_text:
        try:
            ids.append(int(p))
        except:
            await message.reply(f"Invalid ID: {p}")
            return
    asyncio.create_task(broadcast_task(message, ids, None))
    await message.reply(f"Sending DM to {len(ids)} users...")

# -------------------------------------------------------------------
# Callback handlers
# -------------------------------------------------------------------

@dp.callback_query(F.data == "check_join")
async def callback_check_join(callback: CallbackQuery):
    if await check_force_join(callback.from_user.id):
        await callback.message.edit_text("✅ You have joined both channels. You can now use the bot.")
        await callback.answer()
    else:
        await callback.answer("Still missing one or both channels.", show_alert=True)

@dp.callback_query(F.data == "copy")
async def callback_copy(callback: CallbackQuery):
    await callback.answer("Tap and copy the text above.", show_alert=False)

# -------------------------------------------------------------------
# Self-ping task
# -------------------------------------------------------------------

async def self_ping_task_func(base_url: str):
    """Periodically ping the health endpoint to prevent sleeping."""
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(base_url, timeout=10) as resp:
                    logger.info(f"Self-ping to {base_url} returned {resp.status}")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")
        await asyncio.sleep(600)  # 10 minutes

# -------------------------------------------------------------------
# Error handler
# -------------------------------------------------------------------

@dp.error()
async def errors_handler(event: aiogram.types.ErrorEvent):
    logger.error(f"Bot error: {event.exception}", exc_info=True)

# -------------------------------------------------------------------
# Webhook setup and aiohttp app
# -------------------------------------------------------------------

async def on_startup():
    global db, self_ping_task
    # Ensure directory for database exists
    db_path = os.getenv("DATABASE_PATH", "bot_database.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = await Database.create(db_path)
    await db.init_db()
    # Set webhook
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logger.error("WEBHOOK_URL not set")
        return
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook set to {webhook_url}")
    # Start self-ping task using base domain
    parsed = urlparse(webhook_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    if base_url:
        self_ping_task = asyncio.create_task(self_ping_task_func(base_url))
        logger.info(f"Self-ping task started, pinging {base_url} every 10 minutes")

async def on_shutdown():
    # Delete webhook
    await bot.delete_webhook()
    # Cancel self-ping task
    if self_ping_task:
        self_ping_task.cancel()
    await db.close()
    logger.info("Webhook deleted, self-ping stopped, and DB closed")

async def handle_webhook(request: web.Request) -> web.Response:
    """Handle incoming Telegram update."""
    try:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500)

async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="Bot running")

def create_app():
    app = web.Application()
    app.router.add_post(f"/webhook/{BOT_TOKEN}", handle_webhook)
    app.router.add_get("/", health_check)
    app.on_startup.append(lambda _: on_startup())
    app.on_shutdown.append(lambda _: on_shutdown())
    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    web.run_app(create_app(), host="0.0.0.0", port=port)
