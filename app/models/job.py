"""
Job 数据库操作（aiosqlite）
"""
import uuid
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, List
from app.config import settings
import os

DB_PATH = os.path.join(settings.data_dir, "jobs.db")

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    stage           TEXT DEFAULT '',
    progress        INTEGER DEFAULT 0,
    message         TEXT DEFAULT '',

    pdf_filename    TEXT,
    pdf_path        TEXT,
    video_title     TEXT,

    video_path      TEXT,
    video_duration  REAL,
    video_size      INTEGER,

    target_duration INTEGER DEFAULT 60,
    speech_rate     INTEGER DEFAULT 0,
    resolution      TEXT DEFAULT '1920x1080',

    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_SQL)
        await db.commit()


async def create_job(pdf_filename: str, pdf_path: str) -> str:
    job_id = str(uuid.uuid4())
    now = _now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO jobs (id, status, stage, progress, message,
               pdf_filename, pdf_path, created_at, updated_at)
               VALUES (?, 'pending', 'pending', 0, '', ?, ?, ?, ?)""",
            (job_id, pdf_filename, pdf_path, now, now),
        )
        await db.commit()
    return job_id


async def update_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    video_path: Optional[str] = None,
    video_duration: Optional[float] = None,
    video_size: Optional[int] = None,
    video_title: Optional[str] = None,
):
    fields = {"updated_at": _now()}
    if status is not None:
        fields["status"] = status
    if stage is not None:
        fields["stage"] = stage
    if progress is not None:
        fields["progress"] = progress
    if message is not None:
        fields["message"] = message
    if error is not None:
        fields["error"] = error
    if video_path is not None:
        fields["video_path"] = video_path
    if video_duration is not None:
        fields["video_duration"] = video_duration
    if video_size is not None:
        fields["video_size"] = video_size
    if video_title is not None:
        fields["video_title"] = video_title
    if status == "done":
        fields["completed_at"] = _now()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def get_job(job_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_jobs(page: int = 1, limit: int = 10) -> tuple[List[dict], int]:
    offset = (page - 1) * limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM jobs") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows], total


async def delete_job(job_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await db.commit()
        return cur.rowcount > 0
