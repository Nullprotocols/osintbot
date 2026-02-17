import sqlite3
import csv
import io
from datetime import datetime, timedelta

DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  joined_date TEXT,
                  is_banned INTEGER DEFAULT 0,
                  is_admin INTEGER DEFAULT 0,
                  is_owner INTEGER DEFAULT 0,
                  referred_by INTEGER DEFAULT NULL)''')
    # Logs table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  command TEXT,
                  timestamp TEXT,
                  result TEXT)''')
    # Broadcast history (optional)
    c.execute('''CREATE TABLE IF NOT EXISTS broadcasts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER,
                  message TEXT,
                  type TEXT,
                  timestamp TEXT)''')
    conn.commit()
    conn.close()

# ---------- User Management ----------
def add_user(user_id, username, first_name, last_name, referred_by=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT OR IGNORE INTO users 
                 (user_id, username, first_name, last_name, joined_date, referred_by)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, username, first_name, last_name, now, referred_by))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def update_user_activity(user_id):
    # हर बार जब यूजर कमांड करे तो joined_date को अपडेट कर सकते हैं (नया फील्ड last_active)
    # फिलहाल सिर्फ get_user से काम चलेगा
    pass

def ban_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def search_users(query):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT * FROM users WHERE 
                 username LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR user_id LIKE ?''',
              (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
    users = c.fetchall()
    conn.close()
    return users

def get_all_users(limit=10, offset=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY joined_date DESC LIMIT ? OFFSET ?", (limit, offset))
    users = c.fetchall()
    conn.close()
    return users

def count_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_recent_users(days):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE joined_date >= ?", (since,))
    users = c.fetchall()
    conn.close()
    return users

def get_inactive_users(days):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    # यहाँ last_active फील्ड होना चाहिए; अगर नहीं है तो joined_date से अनुमान लगा सकते हैं
    # फिलहाल हम सभी users लौटाते हैं (अपडेट की जरूरत)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE joined_date < ?", (cutoff,))
    users = c.fetchall()
    conn.close()
    return users

def add_admin(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def list_admins():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM users WHERE is_admin=1 OR is_owner=1")
    admins = c.fetchall()
    conn.close()
    return admins

def is_owner(user_id):
    user = get_user(user_id)
    return user and user[6] == 1  # is_owner column index 6 (0-indexed) - adjust if needed

def is_admin(user_id):
    user = get_user(user_id)
    return user and (user[5] == 1 or user[6] == 1)  # is_admin or is_owner

# ---------- Logs ----------
def log_command(user_id, command, result=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO logs (user_id, command, timestamp, result) VALUES (?, ?, ?, ?)",
              (user_id, command, now, result[:500]))  # result truncated
    conn.commit()
    conn.close()

def get_user_logs(user_id, limit=10):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM logs WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
    logs = c.fetchall()
    conn.close()
    return logs

def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_banned = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    total_admins = c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]
    total_logs = c.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    conn.close()
    return total_users, total_banned, total_admins, total_logs

def get_daily_stats(days):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT DATE(timestamp), COUNT(*) FROM logs 
                 WHERE timestamp >= ? GROUP BY DATE(timestamp)''', (since,))
    stats = c.fetchall()
    conn.close()
    return stats

def get_lookup_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT command, COUNT(*) FROM logs GROUP BY command ORDER BY COUNT(*) DESC''')
    stats = c.fetchall()
    conn.close()
    return stats

def get_top_referrers(limit=10):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT referred_by, COUNT(*) FROM users 
                 WHERE referred_by IS NOT NULL GROUP BY referred_by ORDER BY COUNT(*) DESC LIMIT ?''', (limit,))
    top = c.fetchall()
    conn.close()
    return top

# ---------- Backup ----------
def backup_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    conn.close()
    return users

def backup_to_csv():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['user_id','username','first_name','last_name','joined_date','is_banned','is_admin','is_owner','referred_by'])
    writer.writerows(rows)
    return output.getvalue()
