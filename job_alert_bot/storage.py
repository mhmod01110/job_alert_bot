from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .models import JobOpportunity


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ScanRecord:
    completed_at: str
    total_jobs: int
    matched_jobs: int
    new_jobs: int
    warmup_mode: bool


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    job_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    score REAL NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_sent_at TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    completed_at TEXT NOT NULL,
                    total_jobs INTEGER NOT NULL,
                    matched_jobs INTEGER NOT NULL,
                    new_jobs INTEGER NOT NULL,
                    warmup_mode INTEGER NOT NULL
                )
                """
            )
            await db.commit()

    async def subscribe(self, chat_id: int, user_id: int, username: str | None, first_name: str | None) -> None:
        now = utc_now_iso()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO subscribers (chat_id, user_id, username, first_name, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    username=excluded.username,
                    first_name=excluded.first_name,
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, username, first_name, now, now),
            )
            await db.commit()

    async def unsubscribe(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE subscribers SET active=0, updated_at=? WHERE chat_id=?", (utc_now_iso(), chat_id))
            await db.commit()

    async def active_chat_ids(self) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT chat_id FROM subscribers WHERE active=1 ORDER BY created_at ASC")
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]

    async def active_subscriber_count(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM subscribers WHERE active=1")
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def seen_job_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        placeholders = ", ".join("?" for _ in keys)
        query = f"SELECT job_key FROM seen_jobs WHERE job_key IN ({placeholders})"
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query, keys)
            rows = await cursor.fetchall()
        return {str(row[0]) for row in rows}

    async def mark_jobs_seen(self, jobs: list[JobOpportunity], sent: bool) -> None:
        if not jobs:
            return
        now = utc_now_iso()
        async with aiosqlite.connect(self.path) as db:
            for job in jobs:
                await db.execute(
                    """
                    INSERT INTO seen_jobs (job_key, source, title, company, url, score, first_seen_at, last_sent_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_key) DO UPDATE SET
                        score=excluded.score,
                        url=excluded.url,
                        last_sent_at=CASE
                            WHEN excluded.last_sent_at IS NOT NULL THEN excluded.last_sent_at
                            ELSE seen_jobs.last_sent_at
                        END
                    """,
                    (
                        job.key,
                        job.source,
                        job.title,
                        job.company,
                        job.url,
                        job.score,
                        now,
                        now if sent else None,
                    ),
                )
            await db.commit()

    async def has_completed_scan(self) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM scans")
            row = await cursor.fetchone()
        return bool(row[0])

    async def record_scan(self, total_jobs: int, matched_jobs: int, new_jobs: int, warmup_mode: bool) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO scans (completed_at, total_jobs, matched_jobs, new_jobs, warmup_mode)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), total_jobs, matched_jobs, new_jobs, 1 if warmup_mode else 0),
            )
            await db.commit()

    async def latest_scan(self) -> ScanRecord | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT completed_at, total_jobs, matched_jobs, new_jobs, warmup_mode
                FROM scans
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return ScanRecord(
            completed_at=str(row[0]),
            total_jobs=int(row[1]),
            matched_jobs=int(row[2]),
            new_jobs=int(row[3]),
            warmup_mode=bool(row[4]),
        )

