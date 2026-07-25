import aiosqlite
from datetime import datetime, timezone

DB_PATH = "bot_data.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                images_processed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat()


async def record_process(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, images_processed, updated_at) VALUES (?, 1, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 images_processed = images_processed + 1,
                 updated_at = excluded.updated_at""",
            (user_id, _now()),
        )
        await db.commit()


async def get_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT images_processed FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else {"images_processed": 0}
