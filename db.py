import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncpg

from utils.levels import xp_needed


SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id                   BIGINT PRIMARY KEY,
    news_channel_id            BIGINT,
    modlog_channel_id          BIGINT,
    msglog_channel_id          BIGINT,
    voicelog_channel_id        BIGINT,
    levelup_channel_id         BIGINT,
    welcome_channel_id         BIGINT,
    ticket_category_id         BIGINT,
    ticket_role_id             BIGINT,
    ticket_log_channel_id      BIGINT,
    ticket_archive_category_id BIGINT,
    give_role_id               BIGINT,
    promo_role_id              BIGINT
);
CREATE TABLE IF NOT EXISTS users (
    guild_id      BIGINT,
    user_id       BIGINT,
    xp            INTEGER DEFAULT 0,
    level         INTEGER DEFAULT 0,
    coins         BIGINT DEFAULT 0,
    bank          BIGINT DEFAULT 0,
    rep           INTEGER DEFAULT 0,
    messages      INTEGER DEFAULT 0,
    voice_seconds INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS tickets (
    id         SERIAL PRIMARY KEY,
    guild_id   BIGINT,
    channel_id BIGINT,
    user_id    BIGINT,
    topic      TEXT,
    details    TEXT,
    claimed_by BIGINT,
    closed_by  BIGINT,
    rating     INTEGER,
    status     TEXT DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at  TEXT
);
CREATE TABLE IF NOT EXISTS shop_items (
    id          SERIAL PRIMARY KEY,
    guild_id    BIGINT,
    role_id     BIGINT,
    price       BIGINT,
    name        TEXT,
    description TEXT
);
CREATE TABLE IF NOT EXISTS promocodes (
    id          SERIAL PRIMARY KEY,
    guild_id    BIGINT,
    code        TEXT,
    type        INTEGER,
    prize_name  TEXT,
    amount      BIGINT,
    uses_left   INTEGER,
    created_by  BIGINT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    active      INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS promo_redemptions (
    id           SERIAL PRIMARY KEY,
    promocode_id INTEGER,
    guild_id     BIGINT,
    user_id      BIGINT,
    redeemed_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(promocode_id, user_id)
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
    "promo_role_id",
}

# Columns that must exist; applied with ADD COLUMN IF NOT EXISTS on connect,
# so both fresh and pre-existing Postgres databases end up consistent.
_MIGRATE_SETTINGS = [
    "msglog_channel_id BIGINT",
    "voicelog_channel_id BIGINT",
    "levelup_channel_id BIGINT",
    "welcome_channel_id BIGINT",
    "ticket_archive_category_id BIGINT",
    "give_role_id BIGINT",
    "promo_role_id BIGINT",
]
_MIGRATE_TICKETS = [
    "details TEXT",
    "closed_by BIGINT",
    "rating INTEGER",
    "closed_at TEXT",
]
_MIGRATE_USERS = [
    "bank BIGINT DEFAULT 0",
    "rep INTEGER DEFAULT 0",
]
_MIGRATE_SHOP = [
    "description TEXT",
]


def _to_pg(query: str) -> str:
    """Converts '?' positional placeholders (SQLite-style, used throughout
    this codebase) into asyncpg's '$1, $2, ...' style, left to right."""
    parts = query.split("?")
    if len(parts) == 1:
        return query
    out = [parts[0]]
    for i, part in enumerate(parts[1:], start=1):
        out.append(f"${i}")
        out.append(part)
    return "".join(out)


class _RowWrapper(dict):
    """Thin wrapper so callers can do row["col"] like sqlite3.Row/aiosqlite.Row."""
    def __getitem__(self, key):
        return dict.get(self, key)

    def get(self, key, default=None):
        return dict.get(self, key, default)


def _wrap(record):
    if record is None:
        return None
    return _RowWrapper(record)


class _ExecResult:
    """Mimics the subset of aiosqlite's cursor API this codebase relies on:
    .lastrowid and .rowcount."""
    def __init__(self, lastrowid=None, rowcount=0):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=10)
        async with self.pool.acquire() as conn:
            for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
                await conn.execute(statement)
            for col in _MIGRATE_SETTINGS:
                try:
                    await conn.execute(f"ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS {col}")
                except Exception:
                    pass
            for col in _MIGRATE_TICKETS:
                try:
                    await conn.execute(f"ALTER TABLE tickets ADD COLUMN IF NOT EXISTS {col}")
                except Exception:
                    pass
            for col in _MIGRATE_USERS:
                try:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col}")
                except Exception:
                    pass
            for col in _MIGRATE_SHOP:
                try:
                    await conn.execute(f"ALTER TABLE shop_items ADD COLUMN IF NOT EXISTS {col}")
                except Exception:
                    pass

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def execute(self, query: str, *args):
        """Generic write. Returns an object exposing .rowcount."""
        pg_query = _to_pg(query)
        async with self.pool.acquire() as conn:
            status = await conn.execute(pg_query, *args)
        # asyncpg status strings look like "UPDATE 3", "INSERT 0 1", "DELETE 1"
        rowcount = 0
        if status:
            tail = status.strip().split()[-1]
            if tail.isdigit():
                rowcount = int(tail)
        return _ExecResult(lastrowid=None, rowcount=rowcount)

    async def _execute_returning_id(self, query: str, *args) -> int:
        pg_query = _to_pg(query)
        if "RETURNING" not in pg_query.upper():
            pg_query += " RETURNING id"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(pg_query, *args)
        return row["id"] if row else None

    async def fetchone(self, query: str, *args):
        pg_query = _to_pg(query)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(pg_query, *args)
        return _wrap(row)

    async def fetchall(self, query: str, *args):
        pg_query = _to_pg(query)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(pg_query, *args)
        return [_wrap(r) for r in rows]

    async def get_settings(self, guild_id: int):
        return await self.fetchone(
            "SELECT * FROM guild_settings WHERE guild_id=?", guild_id
        )

    async def set_settings(self, guild_id: int, **fields):
        assert fields and set(fields) <= SETTING_FIELDS
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in fields)
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
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET coins=users.coins+?",
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
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET coins=users.coins+?",
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
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET rep=COALESCE(users.rep, 0)+?",
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
        return await self._execute_returning_id(
            "INSERT INTO tickets (guild_id, channel_id, user_id, topic, details) "
            "VALUES (?, 0, ?, ?, ?)",
            guild_id, user_id, topic, details,
        )

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
        return await self._execute_returning_id(
            "INSERT INTO shop_items (guild_id, role_id, price, name, description) VALUES (?, ?, ?, ?, ?)",
            guild_id, role_id, price, name, description,
        )

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

    async def create_promocode(
        self, guild_id: int, code: str, ptype: int,
        prize_name: str | None, amount: int | None,
        uses_left: int, created_by: int,
    ) -> int:
        return await self._execute_returning_id(
            "INSERT INTO promocodes (guild_id, code, type, prize_name, amount, uses_left, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            guild_id, code, ptype, prize_name, amount, uses_left, created_by,
        )

    async def get_promocode(self, guild_id: int, code: str):
        return await self.fetchone(
            "SELECT * FROM promocodes WHERE guild_id=? AND code ILIKE ? AND active=1",
            guild_id, code,
        )

    async def redeem_promocode(self, promocode_id: int, guild_id: int, user_id: int) -> bool:
        """Atomically records a redemption and decrements uses_left.
        Returns True if redemption succeeded, False if already used by this user
        or no uses remain."""
        try:
            await self.execute(
                "INSERT INTO promo_redemptions (promocode_id, guild_id, user_id) VALUES (?, ?, ?)",
                promocode_id, guild_id, user_id,
            )
        except asyncpg.UniqueViolationError:
            return False

        cur = await self.execute(
            "UPDATE promocodes SET uses_left = uses_left - 1 "
            "WHERE id=? AND uses_left > 0",
            promocode_id,
        )
        if cur.rowcount == 0:
            await self.execute(
                "DELETE FROM promo_redemptions WHERE promocode_id=? AND user_id=?",
                promocode_id, user_id,
            )
            return False

        cur2 = await self.fetchone("SELECT uses_left FROM promocodes WHERE id=?", promocode_id)
        if cur2 and cur2["uses_left"] <= 0:
            await self.execute("UPDATE promocodes SET active=0 WHERE id=?", promocode_id)
        return True
