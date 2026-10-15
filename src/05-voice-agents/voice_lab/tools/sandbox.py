"""Sandbox operacional persistente do Graph Engineering Lab com Idempotência e SAGA."""

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from voice_lab.config import settings


class JobRecord(BaseModel):
    job_id: str
    experiment_id: str
    profile: str
    status: str  # pending, running, completed, cancelled, failed
    idempotency_key: str
    created_at: float
    updated_at: float


class OperationalSandbox:
    """Banco de dados SQLite sandbox para simulação e execução verificável de jobs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.artifacts_dir / "sandbox_jobs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
            """)
            conn.commit()

    def trigger_job(self, experiment_id: str, profile: str, idempotency_key: str) -> tuple[JobRecord, bool]:
        """Dispara um job de experimento com garantia de idempotência.
        Retorna (JobRecord, is_new: bool). Se já existia, is_new=False."""
        now = time.time()
        with self._get_connection() as conn:
            # 1. Checar se a idempotency_key já existe
            cursor = conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,))
            row = cursor.fetchone()
            if row:
                record = JobRecord(**dict(row))
                return record, False  # Já existia, idempotência respeitada

            # 2. Inserir novo job
            job_id = f"job_{abs(hash(idempotency_key)) % 100000:05d}"
            conn.execute(
                """
                INSERT INTO jobs (job_id, experiment_id, profile, status, idempotency_key, created_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?, ?)
                """,
                (job_id, experiment_id, profile, idempotency_key, now, now)
            )
            conn.execute(
                "INSERT INTO audit_log (job_id, action, details, timestamp) VALUES (?, 'TRIGGER', ?, ?)",
                (job_id, f"Iniciado experimento {experiment_id} no perfil {profile}", now)
            )
            conn.commit()

            return JobRecord(
                job_id=job_id,
                experiment_id=experiment_id,
                profile=profile,
                status="running",
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now
            ), True

    def cancel_job(self, job_id: str, reason: str, idempotency_key: str) -> tuple[Optional[JobRecord], bool]:
        """Transação compensatória SAGA: cancela um job em andamento."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None, False

            current = dict(row)
            if current["status"] == "cancelled":
                return JobRecord(**current), False  # Já cancelado

            conn.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE job_id = ?",
                (now, job_id)
            )
            conn.execute(
                "INSERT INTO audit_log (job_id, action, details, timestamp) VALUES (?, 'SAGA_COMPENSATION_CANCEL', ?, ?)",
                (job_id, f"Cancelado: {reason} (key: {idempotency_key})", now)
            )
            conn.commit()

            current["status"] = "cancelled"
            current["updated_at"] = now
            return JobRecord(**current), True

    def list_jobs(self, status_filter: Optional[str] = None) -> List[JobRecord]:
        with self._get_connection() as conn:
            if status_filter:
                cursor = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status_filter,))
            else:
                cursor = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            return [JobRecord(**dict(r)) for r in cursor.fetchall()]


sandbox = OperationalSandbox()
