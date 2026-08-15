"""审计运行状态机 + SQLite 状态层（§8.1 / §11）。

- 状态只允许向终态前进，非法转换拒绝；
- 每次转换持久化（WAL）；
- 进程重启后非终态标记 interrupted，由用户决定恢复或重跑。
- 共享状态版本化（R0.2）：每次变更 `version` 单调递增、记录 `written_by`，
  并 append 一条事件到 `events` 表，满足「谁在哪个版本写入了什么」的可追溯。
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
    # R3.2 人工介入：关键节点失败 → 暂停等人工决策。
    ("RUNNING", "HUMAN_WAIT"),
    ("META_REVIEW", "HUMAN_WAIT"),
    ("HUMAN_WAIT", "RUNNING"),
    ("HUMAN_WAIT", "META_REVIEW"),
    ("HUMAN_WAIT", "PARTIAL"),
    ("HUMAN_WAIT", "FAILED"),
}

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "interrupted"}

DEFAULT_WRITER = "argus-cli"

# R3.2 人工介入决策集
HUMAN_DECISIONS = ("retry", "skip", "unknown", "abort")
_HUMAN_RESUME_TARGET = {"retry": "RUNNING", "skip": "PARTIAL",
                        "unknown": "PARTIAL", "abort": "FAILED"}


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
                version INTEGER NOT NULL DEFAULT 0,
                written_by TEXT NOT NULL DEFAULT 'argus-cli',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        # 兼容旧库：version/written_by 列若不存在则补建。
        self._ensure_column("runs", "version", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("runs", "written_by", "TEXT NOT NULL DEFAULT 'argus-cli'")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                writer TEXT NOT NULL,
                action TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                detail TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _next_version(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT version FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        cur = row[0] if row else 0
        return (cur or 0) + 1

    def _append_event(self, run_id: str, version: int, writer: str, action: str,
                      from_status: str | None, to_status: str | None,
                      detail: str) -> None:
        self.conn.execute(
            "INSERT INTO events (run_id, version, writer, action, from_status, "
            "to_status, detail) VALUES (?,?,?,?,?,?,?)",
            (run_id, version, writer, action, from_status, to_status, detail),
        )

    def begin_run(self, writer: str = DEFAULT_WRITER) -> str:
        rid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO runs (run_id, status, version, written_by) "
            "VALUES (?, 'CREATED', 0, ?)", (rid, writer)
        )
        self._append_event(rid, 0, writer, "create", None, "CREATED", "")
        self.conn.commit()
        return rid

    def transition(self, run_id: str, from_: str, to: str,
                   writer: str = DEFAULT_WRITER):
        row = self.conn.execute(
            "SELECT status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        if (from_, to) not in VALID_TRANSITIONS or row[0] != from_:
            raise INVALID_TRANSITION(f"{from_} -> {to} invalid (current={row[0]})")
        version = self._next_version(run_id)
        self.conn.execute(
            "UPDATE runs SET status=?, version=?, written_by=?, "
            "updated_at=datetime('now') WHERE run_id=?",
            (to, version, writer, run_id),
        )
        self._append_event(run_id, version, writer, "transition", from_, to, "")
        self.conn.commit()

    def save_run(self, run_id: str, snapshot_id: str | None = None,
                 gate: str | None = None,
                 base_revision: str | None = None,
                 head_revision: str | None = None,
                 writer: str = DEFAULT_WRITER):
        version = self._next_version(run_id)
        self.conn.execute(
            """UPDATE runs SET
                 snapshot_id=COALESCE(?, snapshot_id),
                 gate=COALESCE(?, gate),
                 base_revision=COALESCE(?, base_revision),
                 head_revision=COALESCE(?, head_revision),
                 version=?, written_by=?,
                 updated_at=datetime('now')
               WHERE run_id=?""",
            (snapshot_id, gate, base_revision, head_revision,
             version, writer, run_id),
        )
        self._append_event(run_id, version, writer, "save", None, None, "metadata")
        self.conn.commit()

    def get_status(self, run_id: str) -> str:
        row = self.conn.execute(
            "SELECT status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return row[0] if row else "unknown"

    def get_version(self, run_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT version FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return row[0] if row else None

    def get_events(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT seq, version, writer, action, from_status, to_status, "
            "detail, created_at FROM events WHERE run_id=? ORDER BY seq",
            (run_id,),
        ).fetchall()
        cols = ("seq", "version", "writer", "action", "from_status",
                "to_status", "detail", "created_at")
        return [dict(zip(cols, r)) for r in rows]

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT run_id, status, snapshot_id, gate, base_revision, "
            "head_revision, version, written_by FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        cols = ("run_id", "status", "snapshot_id", "gate", "base_revision",
                "head_revision", "version", "written_by")
        return dict(zip(cols, row))

    def mark_interrupted_all(self):
        self.conn.execute(
            "UPDATE runs SET status='interrupted' "
            "WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED','interrupted')"
        )
        self.conn.commit()

    # ---- R3.2 人工介入 ----

    def wait_for_human(self, run_id: str, writer: str = DEFAULT_WRITER):
        """RUNNING/META_REVIEW 中关键节点失败 → 暂停等人工决策。"""
        cur = self.get_status(run_id)
        if cur not in ("RUNNING", "META_REVIEW"):
            raise INVALID_TRANSITION(f"cannot wait for human from {cur!r}")
        self.transition(run_id, cur, "HUMAN_WAIT", writer=writer)

    def _wait_origin(self, run_id: str) -> str:
        row = self.conn.execute(
            "SELECT from_status FROM events WHERE run_id=? AND action='transition' "
            "AND to_status='HUMAN_WAIT' ORDER BY seq DESC LIMIT 1", (run_id,)
        ).fetchone()
        return row[0] if row else "RUNNING"

    def resume(self, run_id: str, decision: str,
               writer: str = DEFAULT_WRITER) -> str:
        """从 HUMAN_WAIT 恢复。decision ∈ retry|skip|unknown|abort。"""
        if decision not in HUMAN_DECISIONS:
            raise ValueError(f"invalid human decision: {decision!r}")
        target = self._wait_origin(run_id) if decision == "retry" \
            else _HUMAN_RESUME_TARGET[decision]
        self.transition(run_id, "HUMAN_WAIT", target, writer=writer)
        if decision == "unknown":
            self.save_run(run_id, gate="unknown", writer=writer)
        return target

    def list_recent(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT run_id, status, snapshot_id, gate, created_at FROM runs "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = ("run_id", "status", "snapshot_id", "gate", "created_at")
        return [dict(zip(cols, r)) for r in rows]

    def close(self):
        self.conn.close()
