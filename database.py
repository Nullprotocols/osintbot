# database.py
import aiosqlite
import csv
import io
import os
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = None

    @classmethod
    async def create(cls, db_path="bot_database.sqlite"):
        """Factory method to create and initialize database instance."""
        # Allow override via environment (useful for Render persistent disk)
        persistent_path = os.getenv("DATABASE_PATH")
        if persistent_path:
            db_path = persistent_path
        self = cls(db_path)
        self.connection = await aiosqlite.connect(db_path)
        # Enable foreign keys if needed (optional)
        await self.connection.execute("PRAGMA foreign_keys = ON")
        return self

    async def init_db(self):
        """Create all necessary tables if they don't exist."""
        # Users table (as used in main.py)
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                first_seen TEXT,
                last_seen TEXT,
                total_lookups INTEGER DEFAULT 0
            )
        ''')
        # Admins table (separate from users)
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        # Banned users table
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS banned (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        # Individual lookups log
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS lookups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                command TEXT,
                query TEXT,
                timestamp TEXT
            )
        ''')
        # Daily statistics
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT,
                command TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (date, command)
            )
        ''')
        # Broadcasts (optional, from original)
        await self.connection.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message TEXT,
                type TEXT,
                timestamp TEXT
            )
        ''')
        await self.connection.commit()

    async def execute(self, sql, params=None):
        """Execute a raw SQL query and return a cursor (supports async with)."""
        if params is None:
            params = ()
        return await self.connection.execute(sql, params)

    async def commit(self):
        """Commit the current transaction."""
        await self.connection.commit()

    async def close(self):
        """Close the database connection."""
        if self.connection:
            await self.connection.close()

    # ------------------------------------------------------------------
    # Convenience methods (for future use / compatibility)
    # ------------------------------------------------------------------

    async def add_user(self, user_id, username=None, first_name=None, first_seen=None, last_seen=None):
        """Insert or ignore a user (used by ensure_user_in_db in main.py)."""
        await self.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, first_seen, last_seen, total_lookups) VALUES (?, ?, ?, ?, ?, 0)",
            (user_id, username, first_name, first_seen, last_seen)
        )
        await self.commit()

    async def update_user_last_seen(self, user_id, last_seen, username=None, first_name=None):
        """Update last_seen and optionally username/first_name."""
        await self.execute(
            "UPDATE users SET last_seen = ?, username = COALESCE(?, username), first_name = COALESCE(?, first_name) WHERE user_id = ?",
            (last_seen, username, first_name, user_id)
        )
        await self.commit()

    async def increment_lookups(self, user_id):
        """Increment total_lookups for a user."""
        await self.execute(
            "UPDATE users SET total_lookups = total_lookups + 1 WHERE user_id = ?",
            (user_id,)
        )
        await self.commit()

    async def log_lookup(self, user_id, command, query):
        """Insert a lookup record into lookups table."""
        now = datetime.utcnow().isoformat()
        await self.execute(
            "INSERT INTO lookups (user_id, command, query, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, command, query, now)
        )
        await self.commit()

    async def update_daily_stats(self, command):
        """Increment daily stats for a command."""
        today = datetime.utcnow().date().isoformat()
        await self.execute(
            "INSERT INTO daily_stats (date, command, count) VALUES (?, ?, 1) ON CONFLICT(date, command) DO UPDATE SET count = count + 1",
            (today, command)
        )
        await self.commit()

    # User management
    async def get_user(self, user_id):
        cursor = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()

    async def get_all_users(self, limit=10, offset=0):
        cursor = await self.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset))
        return await cursor.fetchall()

    async def count_users(self):
        cursor = await self.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def search_users(self, query):
        cursor = await self.execute(
            "SELECT * FROM users WHERE user_id LIKE ? OR username LIKE ? OR first_name LIKE ?",
            (f'%{query}%', f'%{query}%', f'%{query}%')
        )
        return await cursor.fetchall()

    async def get_recent_users(self, days):
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        cursor = await self.execute("SELECT * FROM users WHERE last_seen >= ?", (since,))
        return await cursor.fetchall()

    async def get_inactive_users(self, days):
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        cursor = await self.execute("SELECT * FROM users WHERE last_seen < ?", (cutoff,))
        return await cursor.fetchall()

    async def delete_user(self, user_id):
        await self.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await self.commit()

    # Admin management
    async def add_admin(self, user_id):
        await self.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await self.commit()

    async def remove_admin(self, user_id):
        await self.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await self.commit()

    async def list_admins(self):
        cursor = await self.execute("SELECT user_id FROM admins")
        return await cursor.fetchall()

    async def is_admin(self, user_id):
        cursor = await self.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None

    # Ban management
    async def ban_user(self, user_id):
        await self.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (user_id,))
        await self.commit()

    async def unban_user(self, user_id):
        await self.execute("DELETE FROM banned WHERE user_id = ?", (user_id,))
        await self.commit()

    async def is_banned(self, user_id):
        cursor = await self.execute("SELECT user_id FROM banned WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None

    # Lookups / logs
    async def get_user_lookups(self, user_id, limit=20):
        cursor = await self.execute(
            "SELECT command, query, timestamp FROM lookups WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()

    async def get_lookup_stats(self):
        cursor = await self.execute("SELECT command, COUNT(*) FROM lookups GROUP BY command ORDER BY COUNT(*) DESC")
        return await cursor.fetchall()

    async def get_daily_stats(self, date=None):
        if date is None:
            date = datetime.utcnow().date().isoformat()
        cursor = await self.execute("SELECT command, count FROM daily_stats WHERE date = ?", (date,))
        return await cursor.fetchall()

    async def get_overall_stats(self):
        total_users = await self.count_users()
        cursor = await self.execute("SELECT COUNT(*) FROM lookups")
        total_lookups = (await cursor.fetchone())[0]
        return total_users, total_lookups

    # Broadcasts (from original)
    async def log_broadcast(self, admin_id, message, msg_type):
        now = datetime.utcnow().isoformat()
        await self.execute(
            "INSERT INTO broadcasts (admin_id, message, type, timestamp) VALUES (?, ?, ?, ?)",
            (admin_id, message, msg_type, now)
        )
        await self.commit()

    # Backup
    async def backup_users_csv(self):
        """Return CSV string of all users."""
        users = await self.get_all_users(limit=1000000)  # get all
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['user_id', 'username', 'first_name', 'first_seen', 'last_seen', 'total_lookups'])
        for u in users:
            writer.writerow(u)
        return output.getvalue()
