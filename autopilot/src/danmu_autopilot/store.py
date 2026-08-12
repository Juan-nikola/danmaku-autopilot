"""Small SQLite WAL job store for unattended match analysis."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import aiosqlite


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    idempotency_key: str
    payload: dict[str, Any]
    status: str = "queued"
    attempts: int = 0
    worker: str | None = None
    lease_until: float | None = None


class JobStore:
    def __init__(self, path: str | Path, clock: Callable[[], float] | None = None) -> None:
        self.path = Path(path)
        self.clock = clock or time.time
        self.db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                worker TEXT,
                lease_until REAL,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("JobStore.initialize() must be called first")
        return self.db

    @staticmethod
    def _row(row: aiosqlite.Row | tuple[Any, ...]) -> Job:
        values = tuple(row)
        return Job(values[0], values[1], json.loads(values[2]), values[3], values[4], values[5], values[6])

    async def enqueue(self, idempotency_key: str, payload: dict[str, Any]) -> Job:
        db = self._require_db()
        now = self.clock()
        job_id = str(uuid.uuid4())
        await db.execute(
            "INSERT OR IGNORE INTO jobs(id,idempotency_key,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (job_id, idempotency_key, json.dumps(payload, ensure_ascii=False), "queued", now, now),
        )
        await db.commit()
        cursor = await db.execute("SELECT id,idempotency_key,payload,status,attempts,worker,lease_until FROM jobs WHERE idempotency_key=?", (idempotency_key,))
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        return self._row(row)

    async def claim(self, worker: str, lease_seconds: float = 60.0) -> Job | None:
        db = self._require_db()
        now = self.clock()
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT id,idempotency_key,payload,status,attempts,worker,lease_until FROM jobs WHERE status IN ('queued','retry_wait') OR (status='running' AND lease_until<?) ORDER BY created_at LIMIT 1",
            (now,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            await db.commit()
            return None
        job_id = row[0]
        await db.execute(
            "UPDATE jobs SET status='running',worker=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?",
            (worker, now + lease_seconds, now, job_id),
        )
        await db.commit()
        cursor = await db.execute("SELECT id,idempotency_key,payload,status,attempts,worker,lease_until FROM jobs WHERE id=?", (job_id,))
        claimed = await cursor.fetchone()
        await cursor.close()
        return self._row(claimed) if claimed else None

    async def succeed(self, job_id: str) -> None:
        db = self._require_db()
        await db.execute("UPDATE jobs SET status='succeeded',lease_until=NULL,updated_at=? WHERE id=?", (self.clock(), job_id))
        await db.commit()

    async def get(self, job_id: str) -> Job | None:
        db = self._require_db()
        cursor = await db.execute("SELECT id,idempotency_key,payload,status,attempts,worker,lease_until FROM jobs WHERE id=?", (job_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return self._row(row) if row else None

    async def retry(self, job_id: str, error: str = "") -> None:
        db = self._require_db()
        await db.execute("UPDATE jobs SET status='retry_wait',last_error=?,lease_until=NULL,updated_at=? WHERE id=?", (error[:1000], self.clock(), job_id))
        await db.commit()

    async def fail(self, job_id: str, error: str = "") -> None:
        db = self._require_db()
        await db.execute("UPDATE jobs SET status='failed',last_error=?,lease_until=NULL,updated_at=? WHERE id=?", (error[:1000], self.clock(), job_id))
        await db.commit()
