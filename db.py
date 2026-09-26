import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aiosqlite

from utils.levels import xp_needed


SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id                   INTEGER PRIMARY KEY,
    news_channel_id            INTEGER,
    modlog_channel_id          INTEGER,
    msglog_channel_id          INTEGER,
    voicelog_channel_id        INTEGER,
    levelup_channel_id         INTEGER,
    welcome_channel_id         INTEGER,
    ticket_category_id         INTEGER,
    ticket_role_id             INTEGER,
    ticket_log_channel_id      INTEGER,
    ticket_archive_category_id INTEGER,
    give_role_id               INTEGER,
    verification_role_id       INTEGER,
    verification_log_channel_id INTEGER
);
CREATE TABLE IF NOT EXISTS users (
    guild_id      INTEGER,
    user_id       INTEGER,
    xp            INTEGER DEFAULT 0,
    level         INTEGER DEFAULT 0,
    coins         INTEGER DEFAULT 0,
    messages      INTEGER DEFAULT 0,
    voice_seconds INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER,
    channel_id INTEGER,
    user_id    INTEGER,
    topic      TEXT,
    details    TEXT,
    claimed_by INTEGER,
    closed_by  INTEGER,
    rating     INTEGER,
    status     TEXT DEFAULT 'open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at  TEXT
);
CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    role_id     INTEGER,
    price       INTEGER,
    name        TEXT,
    description TEXT
);
"""

SETTING_FIELDS = {
    "news_channel_id",
    "modlog_channel_id",
    "msglog_channel_id",
    "voicelog_channel_id",
    "levelup_channel_id",
    "welcome_channel_id",
    "ticket_category_id",
    "ticket_role_id",
    "ticket_log_channel_id",
    "ticket_archive_category_id",
    "give_role_id",
    "verification_role_id",
    "verification_log_channel_id",
}

_MIGRATE_SETTINGS = [
    "msglog_channel_id INTEGER",
    "voicelog_channel_id INTEGER",
    "levelup_channel_id INTEGER",
    "welcome_channel_id INTEGER",
    "ticket_archive_category_id INTEGER",
    "give_role_id INTEGER",
    "verification_role_id INTEGER",
    "verification_log_channel_id INTEGER",
]
_MIGRATE_TICKETS = [
    "details TEXT",
    "closed_by INTEGER",
    "rating INTEGER",
    "closed_at TEXT",
]
_MIGRATE_USERS = [
    "bank INTEGER DEFAULT 0",
    "rep INTEGER DEFAULT 0",
]
_MIGRATE_SHOP = [
    "description TEXT",
]


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        for col in _MIGRATE_SETTINGS:
            try:
                await self.conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {col}")
            except Exception:
                pass
        for col in _MIGRATE_TICKETS:
            try:
                await self.conn.execute(f"ALTER TABLE tickets ADD COLUMN {col}")
            except Exception:
                pass
        for col in _MIGRATE_USERS:
            try:
                await self.conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        for col in _MIGRATE_SHOP:
            try:
                await self.conn.execute(f"ALTER TABLE shop_items ADD COLUMN {col}")
            except Exception:
                pass
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, query: str, *args):
        cur = await self.conn.execute(query, args)
        await self.conn.commit()
        return cur

    async def fetchone(self, query: str, *args):
        async with self.conn.execute(query, args) as cur:
            return await cur.fetchone()

    async def fetchall(self, query: str, *args):
        async with self.conn.execute(query, args) as cur:
            return await cur.fetchall()

    async def get_settings(self, guild_id: int):
        return await self.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id=?", guild_id
        )

    async def set_settings(self, guild_id: int, **fields):
        assert fields and set(fields) <= SETTING_FIELDS
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
        await self.execute(
            f"INSERT INTO guild_settings (guild_id, {cols}) VALUES (?, {placeholders}) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            guild_id, *fields.values(),
        )

    async def get_user(self, guild_id: int, user_id: int) -> dict:
        row = await self.fetchone(
            "SELECT * FROM users WHERE guild_id=? AND user_id=?", guild_id, user_id
        )
        if row:
            d = dict(row)
            d.setdefault("bank", 0)
            d.setdefault("rep", 0)
            return d
        return {"xp": 0, "level": 0, "coins": 0, "bank": 0, "rep": 0, "messages": 0, "voice_seconds": 0}

    async def add_progress(self, guild_id, user_id, xp=0, coins=0, messages=0, voice_seconds=0):
        await self.execute(
            "INSERT INTO users (guild_id, user_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            guild_id, user_id,
        )
        row = await self.fetchone(
            "SELECT xp, level FROM users WHERE guild_id=? AND user_id=?", guild_id, user_id
        )
        total, level, leveled = row["xp"] + xp, row["level"], False
        while total >= xp_needed(level):
            total -= xp_needed(level)
            level += 1
            leveled = True
        await self.execute(
            "UPDATE users SET xp=?, level=?, coins=coins+?, messages=messages+?, "
            "voice_seconds=voice_seconds+? WHERE guild_id=? AND user_id=?",
            total, level, coins, messages, voice_seconds, guild_id, user_id,
        )
        return level, leveled

    async def add_coins(self, guild_id: int, user_id: int, amount: int):
        await self.execute(
            "INSERT INTO users (guild_id, user_id, coins) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET coins=coins+?",
            guild_id, user_id, amount, amount,
        )

    async def transfer_coins(self, guild_id: int, from_user: int, to_user: int, amount: int) -> bool:
        u_from = await self.get_user(guild_id, from_user)
        if u_from["coins"] < amount:
            return False
        await self.execute(
            "UPDATE users SET coins=coins-? WHERE guild_id=? AND user_id=?",
            amount, guild_id, from_user,
        )
        await self.execute(
            "INSERT INTO users (guild_id, user_id, coins) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET coins=coins+?",
            guild_id, to_user, amount, amount,
        )
        return True

    async def deposit(self, guild_id: int, user_id: int, amount: int) -> bool:
        u = await self.get_user(guild_id, user_id)
        if u["coins"] < amount:
            return False
        await self.execute(
            "UPDATE users SET coins=coins-?, bank=COALESCE(bank, 0)+? WHERE guild_id=? AND user_id=?",
            amount, amount, guild_id, user_id,
        )
        return True

    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> bool:
        u = await self.get_user(guild_id, user_id)
        if u.get("bank", 0) < amount:
            return False
        await self.execute(
            "UPDATE users SET coins=coins+?, bank=COALESCE(bank, 0)-? WHERE guild_id=? AND user_id=?",
            amount, amount, guild_id, user_id,
        )
        return True

    async def add_rep(self, guild_id: int, user_id: int, amount: int = 1):
        await self.execute(
            "INSERT INTO users (guild_id, user_id, rep) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET rep=COALESCE(rep, 0)+?",
            guild_id, user_id, amount, amount,
        )

    async def get_ranks(self, guild_id: int, u: dict):
        by_level = await self.fetchone(
            "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? "
            "AND (level>? OR (level=? AND xp>?))",
            guild_id, u["level"], u["level"], u["xp"],
        )
        total_coins = u["coins"] + u.get("bank", 0)
        by_coins = await self.fetchone(
            "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND (coins + COALESCE(bank, 0))>?",
            guild_id, total_coins,
        )
        by_voice = await self.fetchone(
            "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND voice_seconds>?",
            guild_id, u["voice_seconds"],
        )
        return by_level["r"], by_coins["r"], by_voice["r"]

    async def get_top(self, guild_id: int, sort_by: str, limit: int = 10, offset: int = 0):
        order = {
            "level": "level DESC, xp DESC",
            "coins": "(coins + COALESCE(bank, 0)) DESC",
            "voice": "voice_seconds DESC",
            "rep": "COALESCE(rep, 0) DESC",
            "messages": "messages DESC",
        }.get(sort_by, "level DESC, xp DESC")
        return await self.fetchall(
            f"SELECT * FROM users WHERE guild_id=? ORDER BY {order} LIMIT ? OFFSET ?",
            guild_id, limit, offset,
        )

    async def count_users(self, guild_id: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE guild_id=?", guild_id
        )
        return row["c"] if row else 0

    async def get_user_rank(self, guild_id: int, user_id: int, sort_by: str) -> int:
        u = await self.get_user(guild_id, user_id)
        if sort_by == "level":
            row = await self.fetchone(
                "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? "
                "AND (level>? OR (level=? AND xp>?))",
                guild_id, u["level"], u["level"], u["xp"],
            )
        elif sort_by == "coins":
            total_coins = u["coins"] + u.get("bank", 0)
            row = await self.fetchone(
                "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND (coins + COALESCE(bank, 0))>?",
                guild_id, total_coins,
            )
        elif sort_by == "voice":
            row = await self.fetchone(
                "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND voice_seconds>?",
                guild_id, u["voice_seconds"],
            )
        elif sort_by == "rep":
            row = await self.fetchone(
                "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND COALESCE(rep, 0)>?",
                guild_id, u.get("rep", 0),
            )
        elif sort_by == "messages":
            row = await self.fetchone(
                "SELECT COUNT(*)+1 AS r FROM users WHERE guild_id=? AND messages>?",
                guild_id, u["messages"],
            )
        else:
            return 0
        return row["r"] if row else 0

    async def create_ticket(self, guild_id, user_id, topic, details=None):
        cur = await self.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, topic, details) "
            "VALUES (?, 0, ?, ?, ?)",
            guild_id, user_id, topic, details,
        )
        return cur.lastrowid

    async def get_open_ticket(self, guild_id: int, user_id: int):
        return await self.fetchone(
            "SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            guild_id, user_id,
        )

    async def get_ticket_by_channel(self, channel_id: int):
        return await self.fetchone(
            "SELECT * FROM tickets WHERE channel_id=? AND status='open'", channel_id
        )

    async def update_ticket(self, ticket_id: int, **fields):
        sets = ", ".join(f"{k}=?" for k in fields)
        await self.execute(
            f"UPDATE tickets SET {sets} WHERE id=?", *fields.values(), ticket_id
        )

    async def add_shop_item(self, guild_id: int, role_id: int | None, price: int, name: str, description: str | None = None):
        cur = await self.execute(
            "INSERT INTO shop_items (guild_id, role_id, price, name, description) VALUES (?, ?, ?, ?, ?)",
            guild_id, role_id, price, name, description,
        )
        return cur.lastrowid

    async def get_shop_items(self, guild_id: int):
        return await self.fetchall(
            "SELECT * FROM shop_items WHERE guild_id=? ORDER BY price ASC", guild_id
        )

    async def get_shop_item(self, item_id: int, guild_id: int):
        return await self.fetchone(
            "SELECT * FROM shop_items WHERE id=? AND guild_id=?", item_id, guild_id
        )

    async def remove_shop_item(self, item_id: int, guild_id: int) -> bool:
        cur = await self.execute(
            "DELETE FROM shop_items WHERE id=? AND guild_id=?", item_id, guild_id
        )
        return cur.rowcount > 0
