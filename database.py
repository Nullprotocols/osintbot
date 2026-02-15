import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DATABASE_URL", "sqlite:///bot.db").replace("sqlite:///", "")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Users table with last_used column
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                credits INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                referrals INTEGER DEFAULT 0,
                codes_claimed INTEGER DEFAULT 0,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            )
        """)
        # Referrals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            )
        """)
        # Codes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY,
                amount INTEGER,
                max_uses INTEGER,
                uses INTEGER DEFAULT 0,
                expiry TIMESTAMP,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            )
        """)
        # Redeemed codes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS redeemed_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                code TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (code) REFERENCES codes(code)
            )
        """)
        # Lookups table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lookups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                command TEXT,
                input TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        # Settings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Insert default settings if not exists
        default_settings = {
            'premium_for_all': '0',
            'free_credits_on_join': '1'
        }
        for k, v in default_settings.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()

# ---------- User functions ----------
def add_user(user_id, username, first_name):
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user_id, username, first_name))
        conn.commit()

def update_last_used(user_id):
    with get_db() as conn:
        conn.execute("UPDATE users SET last_used = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        conn.commit()

def update_user(user_id, username=None, first_name=None):
    with get_db() as conn:
        if username:
            conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        if first_name:
            conn.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        conn.commit()

def get_user(user_id):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(user) if user else None

def add_credits(user_id, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET credits = credits + ?, total_earned = total_earned + ? WHERE user_id = ?", (amount, amount, user_id))
        conn.commit()

def deduct_credit(user_id):
    with get_db() as conn:
        conn.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def has_credits(user_id):
    user = get_user(user_id)
    return user and user['credits'] > 0

def set_credits(user_id, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET credits = ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def ban_user(user_id):
    with get_db() as conn:
        conn.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def unban_user(user_id):
    with get_db() as conn:
        conn.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()

def is_banned(user_id):
    user = get_user(user_id)
    return user and user['banned'] == 1

def set_admin(user_id, admin=1):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (admin, user_id))
        conn.commit()

def is_admin(user_id):
    user = get_user(user_id)
    return user and (user['is_admin'] == 1 or user['user_id'] == int(os.getenv('OWNER_ID')))

def get_all_users():
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits, total_earned, referrals, codes_claimed, joined_date, last_used, banned, is_admin FROM users").fetchall()
        return [dict(row) for row in rows]

def get_users_page(page=1, per_page=10):
    offset = (page - 1) * per_page
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits, total_earned, referrals, codes_claimed, joined_date, last_used, banned, is_admin FROM users ORDER BY joined_date DESC LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()['count']
        return [dict(row) for row in rows], total

def search_users(query):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits, total_earned, referrals, codes_claimed, joined_date, last_used, banned, is_admin FROM users WHERE user_id LIKE ? OR username LIKE ? OR first_name LIKE ?", (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
        return [dict(row) for row in rows]

def get_recent_users(days):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, joined_date FROM users WHERE joined_date >= datetime('now', ?)", (f'-{days} days',)).fetchall()
        return [dict(row) for row in rows]

def get_user_lookups(user_id):
    with get_db() as conn:
        rows = conn.execute("SELECT command, input, timestamp, success FROM lookups WHERE user_id = ? ORDER BY timestamp DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]

def get_leaderboard(limit=10):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits FROM users ORDER BY credits DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

def get_premium_users(threshold=100):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits FROM users WHERE credits >= ? ORDER BY credits DESC", (threshold,)).fetchall()
        return [dict(row) for row in rows]

def get_low_credit_users(threshold=10):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, credits FROM users WHERE credits < ? ORDER BY credits ASC", (threshold,)).fetchall()
        return [dict(row) for row in rows]

def get_inactive_users(days):
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, username, first_name, last_used FROM users WHERE last_used < datetime('now', ?)", (f'-{days} days',)).fetchall()
        return [dict(row) for row in rows]

# ---------- Referral functions ----------
def add_referral(referrer_id, referred_id):
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
            conn.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (referrer_id,))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def get_referral_count(user_id):
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id = ?", (user_id,)).fetchone()['cnt']
        return count

# ---------- Code functions ----------
def create_code(code, amount, max_uses, expiry, created_by):
    with get_db() as conn:
        conn.execute("INSERT INTO codes (code, amount, max_uses, expiry, created_by) VALUES (?, ?, ?, ?, ?)", (code, amount, max_uses, expiry, created_by))
        conn.commit()

def get_code(code):
    with get_db() as conn:
        c = conn.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
        return dict(c) if c else None

def redeem_code(user_id, code):
    with get_db() as conn:
        code_data = get_code(code)
        if not code_data or not code_data['active']:
            return False, "Code inactive"
        if code_data['uses'] >= code_data['max_uses']:
            return False, "Max uses reached"
        if code_data['expiry'] and datetime.now() > datetime.fromisoformat(code_data['expiry']):
            return False, "Code expired"
        # Check if user already redeemed this code
        already = conn.execute("SELECT 1 FROM redeemed_codes WHERE user_id = ? AND code = ?", (user_id, code)).fetchone()
        if already:
            return False, "Already redeemed"
        conn.execute("UPDATE codes SET uses = uses + 1 WHERE code = ?", (code,))
        conn.execute("INSERT INTO redeemed_codes (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.execute("UPDATE users SET credits = credits + ?, codes_claimed = codes_claimed + 1 WHERE user_id = ?", (code_data['amount'], user_id))
        conn.commit()
        return True, code_data['amount']

def list_codes(active_only=True):
    with get_db() as conn:
        if active_only:
            rows = conn.execute("SELECT * FROM codes WHERE active = 1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM codes").fetchall()
        return [dict(row) for row in rows]

def deactivate_code(code):
    with get_db() as conn:
        conn.execute("UPDATE codes SET active = 0 WHERE code = ?", (code,))
        conn.commit()

def get_code_stats(code):
    with get_db() as conn:
        redeemed = conn.execute("SELECT COUNT(*) as cnt FROM redeemed_codes WHERE code = ?", (code,)).fetchone()['cnt']
        code_data = get_code(code)
        if code_data:
            return {
                'total_uses': code_data['uses'],
                'redeemed_count': redeemed,
                'amount': code_data['amount'],
                'max_uses': code_data['max_uses'],
                'expiry': code_data['expiry'],
                'active': code_data['active']
            }
        return None

def check_expired_codes():
    with get_db() as conn:
        now = datetime.now().isoformat()
        expired = conn.execute("SELECT code FROM codes WHERE expiry < ? AND active = 1", (now,)).fetchall()
        return [row['code'] for row in expired]

def clean_expired_codes():
    with get_db() as conn:
        now = datetime.now().isoformat()
        conn.execute("UPDATE codes SET active = 0 WHERE expiry < ? AND active = 1", (now,))
        conn.commit()

# ---------- Lookup functions ----------
def log_lookup(user_id, command, input_val, success=True):
    with get_db() as conn:
        conn.execute("INSERT INTO lookups (user_id, command, input, success) VALUES (?, ?, ?, ?)", (user_id, command, input_val, 1 if success else 0))
        conn.commit()

def get_lookup_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM lookups").fetchone()['cnt']
        successful = conn.execute("SELECT COUNT(*) as cnt FROM lookups WHERE success = 1").fetchone()['cnt']
        return total, successful

# ---------- Settings functions ----------
def get_setting(key, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else default

def set_setting(key, value):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def is_premium_for_all():
    return get_setting('premium_for_all', '0') == '1'

def set_premium_for_all(val):
    set_setting('premium_for_all', '1' if val else '0')

def is_free_credits_on_join():
    return get_setting('free_credits_on_join', '1') == '1'

def set_free_credits_on_join(val):
    set_setting('free_credits_on_join', '1' if val else '0')
