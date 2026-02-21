import os
import json
import re
import logging
import csv
import io
import asyncio
from datetime import datetime, timedelta
from typing import Union, Optional, List, Dict, Any

import aiohttp
import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode

# ---------- Environment & Configuration ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing")

OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "8104850843"))
ADMIN_IDS = [
    int(x.strip()) for x in os.environ.get("BOT_ADMIN_IDS", "8104850843,5987905091").split(",")
]
FORCE_CHANNEL1_ID = int(os.environ.get("FORCE_CHANNEL1_ID", "-1003090922367"))
FORCE_CHANNEL2_ID = int(os.environ.get("FORCE_CHANNEL2_ID", "-1003698567122"))
FORCE_CHANNEL1_LINK = os.environ.get("FORCE_CHANNEL1_LINK", "https://t.me/all_data_here")
FORCE_CHANNEL2_LINK = os.environ.get("FORCE_CHANNEL2_LINK", "https://t.me/osint_lookup")

# PostgreSQL connection string (provided by Render)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is missing")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL or RENDER_EXTERNAL_URL must be set")

PORT = int(os.environ.get("PORT", 8080))

# Branding removal (global)
BRANDING_BLACKLIST = [
    '@patelkrish_99', 'patelkrish_99', 't.me/anshapi', 'anshapi',
    '"@Kon_Hu_Mai"', 'Dm to buy access', '"Dm to buy access"', 'Kon_Hu_Mai'
]
# Extra blacklist for number API only
NUMBER_API_BLACKLIST = [
    'dm to buy', 'owner', '@kon_hu_mai',
    'Ruk ja bhencho itne m kya unlimited request lega?? Paid lena h to bolo 100-400₹ @Simpleguy444'
]

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- PostgreSQL Database (async) ----------
class Database:
    _pool: asyncpg.Pool = None

    @classmethod
    async def init_pool(cls):
        """Create a connection pool to PostgreSQL."""
        cls._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        await cls.create_tables()

    @classmethod
    async def close_pool(cls):
        """Close the connection pool."""
        if cls._pool:
            await cls._pool.close()

    @classmethod
    async def create_tables(cls):
        """Create necessary tables if they do not exist."""
        async with cls._pool.acquire() as conn:
            # Users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP,
                    is_banned INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0
                )
            ''')
            # Lookups table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS lookups (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    command TEXT,
                    input TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result_summary TEXT
                )
            ''')
            # Ensure initial admins from env are stored
            for admin_id in ADMIN_IDS:
                await conn.execute('''
                    INSERT INTO users (user_id, is_admin)
                    VALUES ($1, 1)
                    ON CONFLICT (user_id) DO UPDATE SET is_admin = 1
                ''', admin_id)
            logger.info("Database tables initialized")

    @classmethod
    async def get_user(cls, user_id: int) -> Optional[Dict[str, Any]]:
        async with cls._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(row) if row else None

    @classmethod
    async def add_or_update_user(cls, user_id: int, username: str = None,
                                 first_name: str = None, last_name: str = None):
        async with cls._pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, last_activity)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_activity = CURRENT_TIMESTAMP
            ''', user_id, username, first_name, last_name)

    @classmethod
    async def update_activity(cls, user_id: int):
        async with cls._pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = $1",
                user_id
            )

    @classmethod
    async def add_lookup(cls, user_id: int, command: str, input_str: str, result_summary: str = ""):
        async with cls._pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO lookups (user_id, command, input, result_summary)
                VALUES ($1, $2, $3, $4)
            ''', user_id, command, input_str, result_summary[:500])

    @classmethod
    async def is_user_banned(cls, user_id: int) -> bool:
        async with cls._pool.acquire() as conn:
            val = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", user_id)
            return bool(val) if val is not None else False

    @classmethod
    async def set_ban(cls, user_id: int, ban: bool):
        async with cls._pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_banned = $1 WHERE user_id = $2",
                1 if ban else 0, user_id
            )

    @classmethod
    async def set_admin(cls, user_id: int, admin: bool):
        async with cls._pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_admin = $1 WHERE user_id = $2",
                1 if admin else 0, user_id
            )

    @classmethod
    async def get_all_users(cls, include_banned: bool = False) -> List[Dict[str, Any]]:
        async with cls._pool.acquire() as conn:
            if include_banned:
                rows = await conn.fetch("SELECT * FROM users")
            else:
                rows = await conn.fetch("SELECT * FROM users WHERE is_banned = 0")
            return [dict(r) for r in rows]

    @classmethod
    async def get_user_lookups(cls, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT command, input, timestamp FROM lookups
                WHERE user_id = $1
                ORDER BY timestamp DESC LIMIT $2
            ''', user_id, limit)
            return [dict(r) for r in rows]

    # Additional admin stats methods (all async)
    @classmethod
    async def get_stats(cls):
        async with cls._pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            total_lookups = await conn.fetchval("SELECT COUNT(*) FROM lookups")
            active_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM lookups")
            return total_users, banned, total_lookups, active_users

    @classmethod
    async def get_lookup_stats_per_command(cls):
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT command, COUNT(*) as cnt FROM lookups
                GROUP BY command ORDER BY cnt DESC
            ''')
            return [(r['command'], r['cnt']) for r in rows]

    @classmethod
    async def get_daily_lookups(cls, days: int):
        data = []
        for i in range(days):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            async with cls._pool.acquire() as conn:
                cnt = await conn.fetchval('''
                    SELECT COUNT(*) FROM lookups WHERE DATE(timestamp) = $1
                ''', day)
                data.append((day, cnt))
        return data

    @classmethod
    async def get_leaderboard(cls, limit: int = 10):
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT user_id, COUNT(*) as cnt FROM lookups
                GROUP BY user_id ORDER BY cnt DESC LIMIT $1
            ''', limit)
            return [dict(r) for r in rows]

    @classmethod
    async def get_inactive_count(cls, days: int):
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        async with cls._pool.acquire() as conn:
            cnt = await conn.fetchval('''
                SELECT COUNT(*) FROM users
                WHERE last_activity < $1 OR last_activity IS NULL
            ''', since)
            return cnt

    @classmethod
    async def get_recent_users(cls, days: int):
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM users WHERE last_activity >= $1 ORDER BY last_activity DESC
            ''', since)
            return [dict(r) for r in rows]

    @classmethod
    async def delete_user(cls, user_id: int):
        async with cls._pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)

    @classmethod
    async def search_users(cls, query: str):
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM users WHERE
                username ILIKE $1 OR first_name ILIKE $1 OR last_name ILIKE $1 OR user_id::text ILIKE $1
                LIMIT 20
            ''', f'%{query}%')
            return [dict(r) for r in rows]

# ---------- FastAPI & Telegram App ----------
app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()

# ---------- Helper Functions ----------
async def is_admin_or_owner(user_id: int) -> bool:
    """Check if user is in DB as admin or is owner."""
    if user_id == OWNER_ID:
        return True
    user = await Database.get_user(user_id)
    return user and user.get("is_admin") == 1

async def check_force_channels(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> (bool, str):
    """Return (ok, message). If not ok, message contains instruction."""
    if user_id == OWNER_ID or await is_admin_or_owner(user_id):
        return True, ""
    try:
        member1 = await context.bot.get_chat_member(FORCE_CHANNEL1_ID, user_id)
        member2 = await context.bot.get_chat_member(FORCE_CHANNEL2_ID, user_id)
        if member1.status in ["left", "kicked"] or member2.status in ["left", "kicked"]:
            msg = (f"❌ **Please join both channels first:**\n"
                   f"🔹 {FORCE_CHANNEL1_LINK}\n"
                   f"🔹 {FORCE_CHANNEL2_LINK}\n"
                   f"Then try again.")
            return False, msg
        return True, ""
    except Exception as e:
        logger.error(f"Force check error: {e}")
        # If bot can't check (e.g. channels not public), allow usage
        return True, ""

async def fetch_api(url: str, params: dict = None) -> dict:
    """Fetch JSON from API with timeout."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"error": f"HTTP {resp.status}"}
        except asyncio.TimeoutError:
            return {"error": "Request timeout"}
        except Exception as e:
            return {"error": str(e)}

def clean_branding(data: Union[dict, list, str], extra_blacklist: list = None) -> Union[dict, list, str]:
    """Recursively remove any blacklisted strings from JSON data."""
    blacklist = BRANDING_BLACKLIST + (extra_blacklist or [])
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            new_dict[k] = clean_branding(v, extra_blacklist)
        return new_dict
    elif isinstance(data, list):
        return [clean_branding(item, extra_blacklist) for item in data]
    elif isinstance(data, str):
        for bad in blacklist:
            data = data.replace(bad, "")
        # Also remove any extra spaces caused by removal
        data = re.sub(r'\s+', ' ', data).strip()
        return data
    else:
        return data

def format_json_output(raw_json: dict, command: str = "") -> str:
    """Convert JSON to pretty string with footer."""
    # First remove unwanted branding globally
    cleaned = clean_branding(raw_json)
    # Then convert to formatted JSON
    pretty = json.dumps(cleaned, indent=2, ensure_ascii=False)
    # Add footer
    footer = "\n\n---\n👨‍💻 developer: @Nullprotocol_X\n⚡ powered_by: NULL PROTOCOL"
    return f"```json\n{pretty}\n```{footer}"

# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await Database.add_or_update_user(
        user.id, user.username, user.first_name, user.last_name
    )
    if update.effective_chat.type == "private":
        # Private chat: suggest group bot
        await update.message.reply_text(
            "🤖 **This bot only works in groups.**\n"
            "Please add me to a group or use @osintfatherNullBot for personal use.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    # Group: welcome message
    await update.message.reply_text(
        "✅ Bot is active!\nUse /help to see all commands.",
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
**Available Commands:**

📱 **Phone / ID Lookups**
/num <10digit> – Phone number details
/tg2num <tg_id> – Telegram ID → phone
/adr <12digit> – Aadhaar info
/ration <12digit> – Ration card details

🚗 **Vehicle**
/vehicle <number> – Vehicle owner info
/vchalan <number> – Vehicle challan info

🌐 **Network**
/ip <ip> – IP geolocation
/email <email> – Email lookup

🎮 **Free Fire**
/ffinfo <uid> – Free Fire profile
/ffban <uid> – Free Fire ban check

🏦 **Finance**
/ifsc <code> – Bank IFSC details
/gst <gst_no> – GST info

📇 **Social Media**
/insta <username> – Instagram info
/tginfo <@username> – Telegram user info
/tginfopro <tg_id> – Telegram pro info
/git <github_user> – GitHub profile

🇮🇳 **India Specific**
/pin <pincode> – Pincode details
/pak <pak_number> – Pakistan number lookup

Admin commands are hidden.
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# Generic API command factory
def make_api_handler(api_url_template, input_processor=None, extra_branding_blacklist=None):
    """Create a command handler for a given API."""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await Database.add_or_update_user(user.id, user.username, user.first_name, user.last_name)
        chat = update.effective_chat

        # Private chat restriction
        if chat.type == "private" and not await is_admin_or_owner(user.id):
            await update.message.reply_text(
                "❌ **This bot only works in groups.**\n"
                "Try @osintfatherNullBot for personal use.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Force channel check for group users (except admins)
        if chat.type in ["group", "supergroup"]:
            ok, msg = await check_force_channels(user.id, context)
            if not ok:
                await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
                return

        # Extract argument
        args = context.args
        if not args:
            await update.message.reply_text(f"Usage: /{context.command[0]} <input>")
            return
        inp = " ".join(args)
        if input_processor:
            inp = input_processor(inp)

        # Construct URL
        url = api_url_template.format(input=inp)

        # Fetch
        raw_data = await fetch_api(url)
        if "error" in raw_data:
            await update.message.reply_text(f"⚠️ API error: {raw_data['error']}")
            return

        # Clean branding
        cleaned = clean_branding(raw_data, extra_blacklist=extra_branding_blacklist)
        output = format_json_output(cleaned, context.command[0])

        # Truncate if too long (Telegram max 4096)
        if len(output) > 4000:
            output = output[:4000] + "\n... (truncated)"

        await update.message.reply_text(output, parse_mode=ParseMode.MARKDOWN)

        # Record lookup
        await Database.add_lookup(user.id, context.command[0], inp, json.dumps(cleaned)[:200])

    return handler

# Define API endpoints
API_ENDPOINTS = {
    "num": ("https://num-free-rootx-jai-shree-ram-14-day.vercel.app/?key=lundkinger&number={input}", None, NUMBER_API_BLACKLIST),
    "tg2num": ("https://tg2num-owner-api.vercel.app/?userid={input}", None, None),
    "adr": ("https://api-ij32.onrender.com/aadhar?match={input}", None, None),
    "ration": ("https://usesirosint.vercel.app/api/family?key=land&aadhar={input}", None, None),
    "vehicle": ("https://vehicle-info-aco-api.vercel.app/info?vehicle={input}", None, None),
    "vchalan": ("https://api.b77bf911.workers.dev/vehicle?registration={input}", None, None),
    "ip": ("https://abbas-apis.vercel.app/api/ip?ip={input}", None, None),
    "email": ("https://abbas-apis.vercel.app/api/email?mail={input}", None, None),
    "ffinfo": ("https://official-free-fire-info.onrender.com/player-info?key=DV_M7-INFO_API&uid={input}", None, None),
    "ffban": ("https://abbas-apis.vercel.app/api/ff-ban?uid={input}", None, None),
    "pin": ("https://api.postalpincode.in/pincode/{input}", None, None),
    "ifsc": ("https://abbas-apis.vercel.app/api/ifsc?ifsc={input}", None, None),
    "gst": ("https://api.b77bf911.workers.dev/gst?number={input}", None, None),
    "insta": ("https://mkhossain.alwaysdata.net/instanum.php?username={input}", None, None),
    "tginfo": ("https://openosintx.vippanel.in/tgusrinfo.php?key=OpenOSINTX-FREE&user={input}", lambda x: x.lstrip('@'), None),
    "tginfopro": ("https://api.b77bf911.workers.dev/telegram?user={input}", None, None),
    "git": ("https://abbas-apis.vercel.app/api/github?username={input}", None, None),
    "pak": ("https://abbas-apis.vercel.app/api/pakistan?number={input}", None, None),
}

# Register API command handlers
for cmd, (url_tpl, proc, extra_blacklist) in API_ENDPOINTS.items():
    telegram_app.add_handler(CommandHandler(cmd, make_api_handler(url_tpl, proc, extra_blacklist)))

# ---------- Admin Commands ----------
async def is_admin_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user and await is_admin_or_owner(user.id)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message with /broadcast to send it to all users.")
        return

    users = await Database.get_all_users(include_banned=False)
    sent = 0
    failed = 0
    for u in users:
        try:
            await context.bot.copy_message(
                chat_id=u['user_id'],
                from_chat_id=update.chat_id,
                message_id=update.message.reply_to_message.message_id
            )
            sent += 1
        except Exception as e:
            failed += 1
    await update.message.reply_text(f"Broadcast completed. Sent: {sent}, Failed: {failed}")

async def dm_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("Usage: /dm <user_id> <text> or reply to a message with /dm <user_id>")
        return

    target_id = None
    text = None
    if context.args:
        target_id = int(context.args[0])
        text = " ".join(context.args[1:]) if len(context.args) > 1 else None
    if update.message.reply_to_message:
        target_id = int(context.args[0]) if context.args else None
        if not target_id:
            await update.message.reply_text("Please provide user ID when replying.")
            return
        try:
            await context.bot.copy_message(
                chat_id=target_id,
                from_chat_id=update.chat_id,
                message_id=update.message.reply_to_message.message_id
            )
            await update.message.reply_text(f"Message sent to {target_id}.")
        except Exception as e:
            await update.message.reply_text(f"Failed: {e}")
        return
    if text and target_id:
        try:
            await context.bot.send_message(chat_id=target_id, text=text)
            await update.message.reply_text(f"Message sent to {target_id}.")
        except Exception as e:
            await update.message.reply_text(f"Failed: {e}")

async def bulk_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("Usage: /bulkdm id1,id2,... <text> or reply with /bulkdm id1,id2,...")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Provide at least IDs.")
        return
    ids_part = args[0]
    text = " ".join(args[1:]) if len(args) > 1 else None
    try:
        ids = [int(x.strip()) for x in ids_part.split(",")]
    except:
        await update.message.reply_text("Invalid ID list. Use comma separated numbers.")
        return
    if update.message.reply_to_message:
        sent = 0
        failed = 0
        for uid in ids:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.chat_id,
                    message_id=update.message.reply_to_message.message_id
                )
                sent += 1
            except:
                failed += 1
        await update.message.reply_text(f"Bulk DM completed. Sent: {sent}, Failed: {failed}")
    elif text:
        sent = 0
        failed = 0
        for uid in ids:
            try:
                await context.bot.send_message(chat_id=uid, text=text)
                sent += 1
            except:
                failed += 1
        await update.message.reply_text(f"Bulk DM completed. Sent: {sent}, Failed: {failed}")
    else:
        await update.message.reply_text("Provide text or reply to a message.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        uid = int(context.args[0])
        await Database.set_ban(uid, True)
        await update.message.reply_text(f"User {uid} banned.")
    except:
        await update.message.reply_text("Invalid ID.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        uid = int(context.args[0])
        await Database.set_ban(uid, False)
        await update.message.reply_text(f"User {uid} unbanned.")
    except:
        await update.message.reply_text("Invalid ID.")

async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /deleteuser <user_id>")
        return
    try:
        uid = int(context.args[0])
        await Database.delete_user(uid)
        await update.message.reply_text(f"User {uid} deleted.")
    except:
        await update.message.reply_text("Invalid ID or error.")

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /searchuser <query> (username or name)")
        return
    query = " ".join(context.args)
    rows = await Database.search_users(query)
    if not rows:
        await update.message.reply_text("No users found.")
        return
    msg = "**Search Results:**\n"
    for u in rows:
        msg += f"🆔 `{u['user_id']}` | @{u.get('username','')} | {u.get('first_name','')} | Banned: {u['is_banned']}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    per_page = 10
    offset = (page-1)*per_page
    async with Database._pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        rows = await conn.fetch("SELECT * FROM users ORDER BY joined_date DESC LIMIT $1 OFFSET $2", per_page, offset)
    msg = f"**Users (page {page} / { (total+per_page-1)//per_page }):**\n"
    for r in rows:
        u = dict(r)
        msg += f"🆔 `{u['user_id']}` | @{u.get('username','')} | {u.get('first_name','')} | Banned: {u['is_banned']}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def recent_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    rows = await Database.get_recent_users(days)
    msg = f"**Active users in last {days} days:** {len(rows)}\n"
    for u in rows[:10]:
        msg += f"🆔 `{u['user_id']}` | Last active: {u['last_activity'][:16] if u['last_activity'] else 'Never'}\n"
    if len(rows) > 10:
        msg += f"... and {len(rows)-10} more"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def user_lookups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /userlookups <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("Invalid ID.")
        return
    lookups = await Database.get_user_lookups(uid, 20)
    if not lookups:
        await update.message.reply_text("No lookups found.")
        return
    msg = f"**Last lookups for {uid}:**\n"
    for l in lookups:
        msg += f"• `{l['command']}` `{l['input']}` at {l['timestamp'][:16]}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    rows = await Database.get_leaderboard(10)
    msg = "**🏆 Leaderboard (most lookups):**\n"
    for i, r in enumerate(rows, 1):
        u = await Database.get_user(r['user_id'])
        name = f"@{u['username']}" if u and u.get('username') else str(r['user_id'])
        msg += f"{i}. {name} – {r['cnt']} lookups\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def inactive_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    days = 30
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    cnt = await Database.get_inactive_count(days)
    await update.message.reply_text(f"Inactive users (no activity in last {days} days): {cnt}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    total_users, banned, total_lookups, active_users = await Database.get_stats()
    msg = (f"**Bot Statistics:**\n"
           f"👥 Total users: {total_users}\n"
           f"🚫 Banned: {banned}\n"
           f"📊 Total lookups: {total_lookups}\n"
           f"📈 Active users (ever used): {active_users}")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def dailystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    data = await Database.get_daily_lookups(days)
    msg = "**Daily Lookups (last {} days):**\n".format(days)
    for day, cnt in reversed(data):
        msg += f"{day}: {cnt}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def lookupstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    rows = await Database.get_lookup_stats_per_command()
    msg = "**Lookup statistics per command:**\n"
    for cmd, cnt in rows:
        msg += f"/{cmd}: {cnt}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    # Generate CSV of all users
    users = await Database.get_all_users(include_banned=True)
    if not users:
        await update.message.reply_text("No users to backup.")
        return
    output = io.StringIO()
    writer = csv.writer(output)
    # Write header
    writer.writerow(users[0].keys())
    for u in users:
        writer.writerow(u.values())
    csv_data = output.getvalue().encode()
    await update.message.reply_document(document=csv_data, filename="users_backup.csv", caption="Users backup")

async def fulldbbackup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    # Since we use PostgreSQL, we can't send the raw file. Instead, send CSV exports.
    # Users CSV
    users = await Database.get_all_users(include_banned=True)
    if users:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(users[0].keys())
        for u in users:
            writer.writerow(u.values())
        csv_data = output.getvalue().encode()
        await update.message.reply_document(document=csv_data, filename="users_export.csv", caption="Users CSV")

    # Lookups CSV (last 1000 for size)
    async with Database._pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM lookups ORDER BY id DESC LIMIT 1000")
    if rows:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow(r.values())
        csv_data = output.getvalue().encode()
        await update.message.reply_document(document=csv_data, filename="lookups_export.csv", caption="Lookups CSV (last 1000)")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Only owner can add admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        uid = int(context.args[0])
        await Database.set_admin(uid, True)
        await update.message.reply_text(f"User {uid} is now admin.")
    except:
        await update.message.reply_text("Invalid ID.")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Only owner can remove admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        uid = int(context.args[0])
        await Database.set_admin(uid, False)
        await update.message.reply_text(f"User {uid} is no longer admin.")
    except:
        await update.message.reply_text("Invalid ID.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_filter(update, context):
        return
    async with Database._pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username FROM users WHERE is_admin = 1")
    msg = "**Admins:**\n"
    for a in rows:
        msg += f"• `{a['user_id']}` (@{a.get('username','')})\n"
    msg += f"👑 Owner: `{OWNER_ID}`"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# Register admin handlers
admin_handlers = [
    ("broadcast", broadcast), ("dm", dm_user), ("bulkdm", bulk_dm),
    ("ban", ban_user), ("unban", unban_user), ("deleteuser", delete_user),
    ("searchuser", search_user), ("users", list_users), ("recentusers", recent_users),
    ("userlookups", user_lookups), ("leaderboard", leaderboard), ("inactiveusers", inactive_users),
    ("stats", stats), ("dailystats", dailystats), ("lookupstats", lookupstats),
    ("backup", backup), ("fulldbbackup", fulldbbackup), ("addadmin", add_admin),
    ("removeadmin", remove_admin), ("listadmins", list_admins)
]
for cmd, handler in admin_handlers:
    telegram_app.add_handler(CommandHandler(cmd, handler))

# ---------- General Message Handler (ignore) ----------
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass  # ignore non-command messages

telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# ---------- Webhook Setup ----------
@app.on_event("startup")
async def on_startup():
    await Database.init_pool()
    await telegram_app.initialize()
    # Set webhook
    webhook_url = WEBHOOK_URL.rstrip('/') + "/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.bot.delete_webhook()
    await telegram_app.shutdown()
    await Database.close_pool()

@app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, telegram_app.bot)
    await telegram_app.process_update(update)
    return Response(status_code=200)

@app.get("/")
async def health():
    return {"status": "ok"}

# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
