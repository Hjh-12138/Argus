"""审计运行状态机 + SQLite 状态层（§8.1 / §11）。

- 状态只允许向终态前进，非法转换拒绝；
- 每次转换持久化（WAL）；
- 进程重启后非终态标记 interrupted，由用户决定恢复或重跑。
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

# 合法转换表（§8.1 run state machine）
VALID_TRANSITIONS = {
    ("CREATED", "PREFLIGHT"),
    ("PREFLIGHT", "SNAPSHOTTING"),
    ("SNAPSHOTTING", "SCHEDULED"),
    ("SCHEDULED", "RUNNING"),
    ("RUNNING", "META_REVIEW"),
    ("META_REVIEW", "SYNTHESIZING"),
    ("SYNTHESIZING", "COMPLETED"),
    ("CREATED", "FAILED"),
    ("PREFLIGHT", "FAILED"),
    ("SNAPSHOTTING", "FAILED"),
    ("SYNTHESIZING", "FAILED"),
    ("RUNNING", "CANCELLED"),
    ("RUNNING", "PARTIAL"),
    ("META_REVIEW", "PARTIAL"),
    ("RUNNING", "CANCELLING"),
    ("CANCELLING", "CANCELLED"),
    ("CANCELLING", "PARTIAL"),
}

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "interrupted"}


class INVALID_TRANSITION(Exception):
    pass


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                snapshot_id TEXT,
                gate TEXT,
                base_revision TEXT,
                head_revision TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self.conn.commit()

    def begin_run(self) -> str:
        rid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO runs (run_id, status) VALUES (?, 'CREATED')", (rid,)
        )
        self.conn.commit()
        return rid

    def transition(self, run_id: str, from_: str, to: str):
        row = self.conn.execute(
            "SELECT status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        if (from_, to) not in VALID_TRANSITIONS or row[0] != from_:
            raise INVALID_TRANSITION(f"{from_} -> {to} invalid (current={row[0]})")
        self.conn.execute(
            "UPDATE runs SET status=?, updated_at=datetime('now') WHERE run_id=?",
            (to, run_id),
        )
        self.conn.commit()

    def save_run(self, run_id: str, snapshot_id: str | None = None,
                 gate: str | None = None,
                 base_revision: str | None = None,
                 head_revision: str | None = None):
        self.conn.execute(
            """UPDATE runs SET
                 snapshot_id=COALESCE(?, snapshot_id),
                 gate=COALESCE(?, gate),
                 base_revision=COALESCE(?, base_revision),
                 head_revision=COALESCE(?, head_revision),
                 updated_at=datetime('now')
               WHERE run_id=?""",
            (snapshot_id, gate, base_revision, head_revision, run_id),
        )
        self.conn.commit()

    def get_status(self, run_id: str) -> str:
        row = self.conn.execute(
            "SELECT status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return row[0] if row else "unknown"

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT run_id, status, snapshot_id, gate, base_revision, head_revision "
            "FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        cols = ("run_id", "status", "snapshot_id", "gate", "base_revision", "head_revision")
        return dict(zip(cols, row))

    def mark_interrupted_all(self):
        self.conn.execute(
            "UPDATE runs SET status='interrupted' "
            "WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED','interrupted')"
        )
        self.conn.commit()

    def list_recent(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT run_id, status, snapshot_id, gate, created_at FROM runs "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = ("run_id", "status", "snapshot_id", "gate", "created_at")
        return [dict(zip(cols, r)) for r in rows]

    def close(self):
        self.conn.close()
