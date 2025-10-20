"""SQLite 기반 영속 스토리지 헬퍼."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import Job, JobStatus, NodeMetadata, RepositorySpec

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    target_node_id TEXT,
    requested_tags TEXT,
    repositories TEXT,
    metadata TEXT,
    log_path TEXT,
    result_summary TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    display_name TEXT,
    tags TEXT,
    capabilities TEXT,
    status TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_logs (
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
);

CREATE TABLE IF NOT EXISTS user_tokens (
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TEXT,
    metadata TEXT,
    PRIMARY KEY (user_id, provider)
);
"""


# NOTE: JobStorage and NodeStorage는 이후 마이그레이션 툴/ORM 도입 시 교체될 수 있음.


class Storage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()
        self._log_seq_cache: dict[str, int] = {}

    def close(self) -> None:
        self._conn.close()

    def _bootstrap(self) -> None:
        with self._conn:
            self._conn.executescript(_DB_SCHEMA)

    # Job CRUD ------------------------------------------------------------

    def upsert_job(self, job: Job) -> None:
        repositories = [repo.__dict__ for repo in job.repositories]
        payload = {
            "job_id": job.job_id,
            "prompt": job.prompt,
            "status": job.status.value,
            "target_node_id": job.target_node_id,
            "requested_tags": json.dumps(job.requested_tags),
            "repositories": json.dumps(repositories),
            "metadata": json.dumps(job.metadata),
            "log_path": job.log_path,
            "result_summary": job.result_summary,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
        columns = ", ".join(payload.keys())
        placeholders = ", ".join([":" + key for key in payload.keys()])
        update_clause = ", ".join([f"{key}=excluded.{key}" for key in payload.keys() if key != "job_id"])
        sql = f"""
        INSERT INTO jobs ({columns})
        VALUES ({placeholders})
        ON CONFLICT(job_id) DO UPDATE SET {update_clause}
        """
        with self._conn:
            self._conn.execute(sql, payload)

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, limit: int = 50, status: JobStatus | None = None) -> list[Job]:
        sql = "SELECT * FROM jobs"
        params: list[object] = []
        if status is not None:
            sql += " WHERE status=?"
            params.append(status.value)
        sql += " ORDER BY datetime(created_at) DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_jobs_by_status(self, statuses: Sequence[JobStatus], limit: int = 100) -> list[Job]:
        if not statuses:
            return []
        placeholders = ", ".join(["?"] * len(statuses))
        sql = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY datetime(created_at) ASC LIMIT ?"
        params = [status.value for status in statuses]
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        log_path: str | None = None,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        columns = {
            "status": status.value,
            "log_path": log_path,
            "result_summary": result_summary,
            "error_message": error_message,
        }
        updates = []
        params: dict[str, object] = {}
        for key, value in columns.items():
            if value is not None:
                updates.append(f"{key} = :{key}")
                params[key] = value

        if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            updates.append("finished_at = datetime('now')")

        if not updates:
            return

        params["job_id"] = job_id
        sql = f"UPDATE jobs SET {' , '.join(updates)} WHERE job_id=:job_id"
        with self._conn:
            self._conn.execute(sql, params)

    def mark_job_queued(self, job_id: str, node_id: str) -> None:
        sql = """
        UPDATE jobs
        SET status = ?, target_node_id = ?
        WHERE job_id = ? AND status IN (?, ?)
        """
        with self._conn:
            self._conn.execute(
                sql,
                (
                    JobStatus.QUEUED.value,
                    node_id,
                    job_id,
                    JobStatus.PENDING.value,
                    JobStatus.QUEUED.value,
                ),
            )

    def assign_job(self, job_id: str, node_id: str) -> bool:
        sql = """
        UPDATE jobs
        SET status = ?, target_node_id = ?, result_summary = ?
        WHERE job_id = ? AND status IN (?, ?)
        """
        with self._conn:
            cursor = self._conn.execute(
                sql,
                (
                    JobStatus.RUNNING.value,
                    node_id,
                    "dispatched",
                    job_id,
                    JobStatus.PENDING.value,
                    JobStatus.QUEUED.value,
                ),
            )
        return cursor.rowcount > 0

    # Job logs ------------------------------------------------------------

    def append_job_log(self, job_id: str, level: str, message: str, timestamp: datetime | None = None) -> None:
        seq = self._log_seq_cache.get(job_id)
        if seq is None:
            row = self._conn.execute("SELECT MAX(seq) FROM job_logs WHERE job_id=?", (job_id,)).fetchone()
            seq = row[0] if row and row[0] is not None else 0
        seq += 1
        self._log_seq_cache[job_id] = seq
        payload = {
            "job_id": job_id,
            "seq": seq,
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "level": level,
            "message": message,
        }
        sql = """
        INSERT INTO job_logs (job_id, seq, timestamp, level, message)
        VALUES (:job_id, :seq, :timestamp, :level, :message)
        """
        with self._conn:
            self._conn.execute(sql, payload)

    def list_job_logs(self, job_id: str, *, limit: int = 200, after_seq: int | None = None) -> list[dict[str, str]]:
        sql = "SELECT * FROM job_logs WHERE job_id=?"
        params: list[object] = [job_id]
        if after_seq is not None:
            sql += " AND seq > ?"
            params.append(after_seq)
        sql += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def set_user_token(
        self,
        user_id: str,
        provider: str,
        *,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "user_id": user_id,
            "provider": provider,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "metadata": json.dumps(metadata or {}),
        }
        sql = """
        INSERT INTO user_tokens (user_id, provider, access_token, refresh_token, expires_at, metadata)
        VALUES (:user_id, :provider, :access_token, :refresh_token, :expires_at, :metadata)
        ON CONFLICT(user_id, provider) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=excluded.refresh_token,
            expires_at=excluded.expires_at,
            metadata=excluded.metadata
        """
        with self._conn:
            self._conn.execute(sql, payload)

    def get_user_token(self, user_id: str, provider: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM user_tokens WHERE user_id=? AND provider=?",
            (user_id, provider),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        metadata_raw = data.get("metadata")
        data["metadata"] = json.loads(metadata_raw) if metadata_raw else {}
        return data

    def dequeue_pending_job(self, candidate_node_id: str | None) -> Job | None:
        sql = "SELECT * FROM jobs WHERE status=? ORDER BY datetime(created_at) ASC LIMIT 1"
        row = self._conn.execute(sql, (JobStatus.QUEUED.value,)).fetchone()
        if not row:
            return None
        job = self._row_to_job(row)
        job.status = JobStatus.RUNNING
        job.target_node_id = candidate_node_id or job.target_node_id
        self.upsert_job(job)
        return job

    # Node metadata --------------------------------------------------------

    def upsert_node(self, node: NodeMetadata) -> None:
        payload = {
            "node_id": node.node_id,
            "display_name": node.display_name,
            "tags": json.dumps(node.tags),
            "capabilities": json.dumps(node.capabilities),
            "status": node.status,
            "last_seen": node.last_seen.isoformat(),
        }
        columns = ", ".join(payload.keys())
        placeholders = ", ".join([":" + key for key in payload.keys()])
        update_clause = ", ".join([f"{key}=excluded.{key}" for key in payload.keys() if key != "node_id"])
        sql = f"""
        INSERT INTO nodes ({columns})
        VALUES ({placeholders})
        ON CONFLICT(node_id) DO UPDATE SET {update_clause}
        """
        with self._conn:
            self._conn.execute(sql, payload)

    def list_nodes(self) -> list[NodeMetadata]:
        rows = self._conn.execute("SELECT * FROM nodes ORDER BY display_name").fetchall()
        return [self._row_to_node(row) for row in rows]

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        repositories = [RepositorySpec(**repo) for repo in json.loads(row["repositories"]) or []]
        requested_tags = json.loads(row["requested_tags"]) or []
        metadata = json.loads(row["metadata"]) or {}
        return Job(
            job_id=row["job_id"],
            prompt=row["prompt"],
            status=JobStatus(row["status"]),
            target_node_id=row["target_node_id"],
            requested_tags=requested_tags,
            repositories=repositories,
            metadata=metadata,
            log_path=row["log_path"],
            result_summary=row["result_summary"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    def _row_to_node(self, row: sqlite3.Row) -> NodeMetadata:
        return NodeMetadata(
            node_id=row["node_id"],
            display_name=row["display_name"],
            tags=json.loads(row["tags"]) or [],
            capabilities=json.loads(row["capabilities"]) or {},
            status=row["status"],
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )


def init_storage(db_path: str | Path) -> Storage:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Storage(path)
