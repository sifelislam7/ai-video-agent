"""Tiny SQLite-backed store for jobs and TikTok accounts.

Deliberately dependency-free (stdlib ``sqlite3``) so the project runs anywhere.
Rows keep their payload as JSON, validated through the pydantic models.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR
from .schemas import (
    Account,
    CreateJobRequest,
    Job,
    JobResult,
    JobStatus,
    LogEntry,
)

DB_PATH = DATA_DIR / "agent.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    status        TEXT NOT NULL,
    progress      INTEGER NOT NULL DEFAULT 0,
    step          TEXT NOT NULL DEFAULT '',
    request_json  TEXT NOT NULL,
    result_json   TEXT,
    logs_json     TEXT NOT NULL DEFAULT '[]',
    error         TEXT,
    scheduled_at  TEXT,
    account_id    TEXT
);
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL DEFAULT '',
    avatar_url    TEXT NOT NULL DEFAULT '',
    access_token  TEXT NOT NULL DEFAULT '',
    refresh_token TEXT NOT NULL DEFAULT '',
    expires_at    TEXT,
    scopes        TEXT NOT NULL DEFAULT '',
    mode          TEXT NOT NULL DEFAULT 'mock',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_sched  ON jobs(scheduled_at);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    """Serialise as UTC ISO-8601 — the scheduler compares these as strings."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class Store:
    """Thread-safe SQLite wrapper (one connection guarded by a lock)."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ jobs
    def create_job(self, req: CreateJobRequest) -> Job:
        now = utcnow()
        job = Job(
            id=uuid.uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            status=JobStatus.QUEUED,
            request=req,
            scheduled_at=req.schedule_at,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, created_at, updated_at, status, progress, step,"
                " request_json, result_json, logs_json, error, scheduled_at, account_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job.id,
                    _iso(now),
                    _iso(now),
                    job.status.value,
                    0,
                    "",
                    req.model_dump_json(),
                    None,
                    "[]",
                    None,
                    _iso(job.scheduled_at),
                    None,
                ),
            )
            self._conn.commit()
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, limit: int = 50, status: str | None = None) -> list[Job]:
        q = "SELECT * FROM jobs"
        args: list[Any] = []
        if status:
            q += " WHERE status = ?"
            args.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [self._row_to_job(r) for r in rows]

    def due_jobs(self, now: datetime | None = None) -> list[Job]:
        """Scheduled jobs whose publish time has arrived."""
        now = now or utcnow()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? AND scheduled_at IS NOT NULL"
                " AND scheduled_at <= ? ORDER BY scheduled_at ASC",
                (JobStatus.SCHEDULED.value, _iso(now)),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        mapping: dict[str, Any] = {}
        for key, value in fields.items():
            if key == "status":
                mapping["status"] = value.value if isinstance(value, JobStatus) else str(value)
            elif key == "result":
                mapping["result_json"] = (
                    value.model_dump_json() if isinstance(value, JobResult) else json.dumps(value)
                )
            elif key == "logs":
                mapping["logs_json"] = json.dumps(
                    [json.loads(e.model_dump_json()) for e in value], ensure_ascii=False
                )
            elif key in {"scheduled_at"}:
                mapping[key] = _iso(value) if isinstance(value, datetime) else value
            else:
                mapping[key] = value
        mapping["updated_at"] = _iso(utcnow())
        sets = ", ".join(f"{k} = ?" for k in mapping)
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {sets} WHERE id = ?", (*mapping.values(), job_id)
            )
            self._conn.commit()

    def append_log(self, job_id: str, step: str, message: str, level: str = "info") -> LogEntry:
        entry = LogEntry(at=utcnow(), level=level, step=step, message=message)
        with self._lock:
            row = self._conn.execute("SELECT logs_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            logs = json.loads(row["logs_json"]) if row and row["logs_json"] else []
            logs.append(json.loads(entry.model_dump_json()))
            logs = logs[-200:]
            self._conn.execute(
                "UPDATE jobs SET logs_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(logs, ensure_ascii=False), _iso(utcnow()), job_id),
            )
            self._conn.commit()
        return entry

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            created_at=_dt(row["created_at"]) or utcnow(),
            updated_at=_dt(row["updated_at"]) or utcnow(),
            status=JobStatus(row["status"]),
            progress=row["progress"] or 0,
            step=row["step"] or "",
            request=CreateJobRequest.model_validate_json(row["request_json"]),
            result=JobResult.model_validate_json(row["result_json"]) if row["result_json"] else None,
            logs=[LogEntry.model_validate(e) for e in json.loads(row["logs_json"] or "[]")],
            error=row["error"],
            scheduled_at=_dt(row["scheduled_at"]),
            account_id=row["account_id"],
        )

    # -------------------------------------------------------------- accounts
    def upsert_account(self, account: Account) -> Account:
        account.created_at = account.created_at or utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO accounts (id, display_name, avatar_url, access_token,"
                " refresh_token, expires_at, scopes, mode, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,"
                " avatar_url=excluded.avatar_url, access_token=excluded.access_token,"
                " refresh_token=excluded.refresh_token, expires_at=excluded.expires_at,"
                " scopes=excluded.scopes, mode=excluded.mode",
                (
                    account.id,
                    account.display_name,
                    account.avatar_url,
                    account.access_token,
                    account.refresh_token,
                    _iso(account.expires_at),
                    account.scopes,
                    account.mode,
                    _iso(account.created_at),
                ),
            )
            self._conn.commit()
        return account

    def list_accounts(self) -> list[Account]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM accounts ORDER BY created_at").fetchall()
        return [self._row_to_account(r) for r in rows]

    def get_account(self, account_id: str | None) -> Account | None:
        if account_id:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM accounts WHERE id = ?", (account_id,)
                ).fetchone()
            return self._row_to_account(row) if row else None
        accounts = self.list_accounts()
        return accounts[0] if accounts else None

    def delete_account(self, account_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            self._conn.commit()

    @staticmethod
    def _row_to_account(row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=_dt(row["expires_at"]),
            scopes=row["scopes"],
            mode=row["mode"],
            created_at=_dt(row["created_at"]),
        )

    # ------------------------------------------------------------------ misc
    def close(self) -> None:
        with self._lock:
            self._conn.close()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def reset_store(path: Path | str | None = None) -> Store:
    """Used by tests to point the store at a temporary database."""
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:  # pragma: no cover - defensive
            pass
    _store = Store(path or DB_PATH)
    return _store


__all__: Iterable[str] = ["Store", "get_store", "reset_store", "utcnow", "DB_PATH"]
