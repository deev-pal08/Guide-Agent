"""SQLite state store for the Guide Agent.

Tables:
- bug_classes        — hierarchy of bug classes (leaf and parent)
- phase_progress     — per-(bug_class, phase) progress ledger
- plans              — proposed/confirmed/sent plans
- tasks              — individual tasks within a plan
- consumed_resources — URLs already covered for a bug class
- feedback_log       — per-task feedback from email or CLI
- user_notes         — persistent general notes from email replies
- meta               — generic key/value store
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS bug_classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        parent_id INTEGER NULL REFERENCES bug_classes(id),
        is_leaf INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'in_progress',
        mastered_at TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_classes_parent
        ON bug_classes(parent_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bug_classes_status
        ON bug_classes(status)
    """,
    """
    CREATE TABLE IF NOT EXISTS phase_progress (
        bug_class_id INTEGER NOT NULL REFERENCES bug_classes(id),
        phase TEXT NOT NULL,
        resources_consumed INTEGER NOT NULL DEFAULT 0,
        last_run TIMESTAMP NULL,
        notes TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (bug_class_id, phase)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bug_class_id INTEGER NOT NULL REFERENCES bug_classes(id),
        phase TEXT NOT NULL,
        research_mode TEXT NULL,
        date TEXT NOT NULL,
        target_hours REAL NOT NULL,
        rationale TEXT NOT NULL DEFAULT '',
        plan_json TEXT NOT NULL DEFAULT '{}',
        tools_section_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'draft',
        proposed_at TIMESTAMP NULL,
        confirmed_at TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plans_bug_class
        ON plans(bug_class_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plans_status
        ON plans(status)
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES plans(id),
        bug_class_id INTEGER NOT NULL REFERENCES bug_classes(id),
        phase TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        task_type TEXT NOT NULL DEFAULT 'read',
        priority TEXT NOT NULL DEFAULT 'high',
        estimated_hours REAL NOT NULL DEFAULT 1.0,
        resource_url TEXT NOT NULL DEFAULT '',
        resource_name TEXT NOT NULL DEFAULT '',
        resources_json TEXT NOT NULL DEFAULT '[]',
        why TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        actual_hours REAL NULL,
        learnings TEXT NOT NULL DEFAULT '',
        assigned_date TIMESTAMP NOT NULL,
        completed_date TIMESTAMP NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tasks_plan
        ON tasks(plan_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tasks_bug_class
        ON tasks(bug_class_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tasks_status
        ON tasks(status)
    """,
    """
    CREATE TABLE IF NOT EXISTS consumed_resources (
        bug_class_id INTEGER NOT NULL REFERENCES bug_classes(id),
        url TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        phase TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'web',
        consumed_at TIMESTAMP NOT NULL,
        PRIMARY KEY (bug_class_id, url)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_consumed_phase
        ON consumed_resources(bug_class_id, phase)
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id),
        status TEXT NOT NULL,
        actual_hours REAL NULL,
        notes TEXT NOT NULL DEFAULT '',
        learnings TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'email',
        received_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_feedback_task
        ON feedback_log(task_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS user_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note TEXT NOT NULL,
        received_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hydrate_task_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialise resources_json into a Python list and surface as `resources`.

    Also surface old-shape aliases so existing consumers keep working:
      row["resources"] = list of {url, name, note} dicts
      row["primary_resource_url"] mirrors row["resource_url"] (legacy column)
      row["primary_resource_name"] mirrors row["resource_name"]
    """
    raw = row.get("resources_json", "") or "[]"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, list):
            parsed = []
    except json.JSONDecodeError:
        parsed = []
    row["resources"] = parsed
    row["primary_resource_url"] = row.get("resource_url", "")
    row["primary_resource_name"] = row.get("resource_name", "")
    return row


def _hydrate_plan_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialise tools_section_json into a list and surface as `tools_section`."""
    raw = row.get("tools_section_json", "") or "[]"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, list):
            parsed = []
    except json.JSONDecodeError:
        parsed = []
    row["tools_section"] = parsed
    return row


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class StateStore:
    """SQLite-backed state for the Guide Agent.

    Auto-creates the database file and runs migrations on init.
    Designed for serial CLI use — no connection pooling needed.
    """

    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "guide.db"
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        for stmt in SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()
        self._migrate_alter_tasks()
        self._migrate_alter_plans()

    def _migrate_alter_plans(self) -> None:
        """Idempotent column-add for existing DBs created before tools_section_json."""
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(plans)").fetchall()
        }
        if "tools_section_json" not in cols:
            self._conn.execute(
                "ALTER TABLE plans ADD COLUMN tools_section_json TEXT NOT NULL DEFAULT '[]'"
            )
            self._conn.commit()

    def _migrate_alter_tasks(self) -> None:
        """Idempotent column-add for existing DBs created before resources_json."""
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "resources_json" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN resources_json TEXT NOT NULL DEFAULT '[]'"
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Bug classes
    # ------------------------------------------------------------------

    def upsert_bug_class(
        self,
        name: str,
        parent_id: int | None = None,
        is_leaf: bool = True,
    ) -> int:
        """Insert or fetch a bug class by name. Returns id."""
        name = name.strip().lower()
        existing = self._conn.execute(
            "SELECT id FROM bug_classes WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = self._conn.execute(
            """INSERT INTO bug_classes (name, parent_id, is_leaf, status, created_at)
               VALUES (?, ?, ?, 'in_progress', ?)""",
            (name, parent_id, 1 if is_leaf else 0, _now()),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def get_bug_class(self, name_or_id: str | int) -> dict[str, Any] | None:
        if isinstance(name_or_id, int):
            row = self._conn.execute(
                "SELECT * FROM bug_classes WHERE id = ?", (name_or_id,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM bug_classes WHERE name = ?",
                (name_or_id.strip().lower(),),
            ).fetchone()
        return dict(row) if row else None

    def get_children(self, parent_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM bug_classes WHERE parent_id = ? ORDER BY name",
            (parent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_in_progress(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM bug_classes WHERE status = 'in_progress' "
            "AND is_leaf = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_mastered(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM bug_classes WHERE status = 'mastered' "
            "ORDER BY mastered_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_mastered(self, bug_class_id: int) -> None:
        self._conn.execute(
            "UPDATE bug_classes SET status = 'mastered', mastered_at = ? WHERE id = ?",
            (_now(), bug_class_id),
        )
        self._conn.commit()

    def mark_in_progress(self, bug_class_id: int) -> None:
        """Resume a previously mastered bug class."""
        self._conn.execute(
            "UPDATE bug_classes SET status = 'in_progress', mastered_at = NULL "
            "WHERE id = ?",
            (bug_class_id,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Phase progress
    # ------------------------------------------------------------------

    def get_phase_progress(
        self, bug_class_id: int, phase: str
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM phase_progress WHERE bug_class_id = ? AND phase = ?",
            (bug_class_id, phase),
        ).fetchone()
        return dict(row) if row else None

    def get_all_phase_progress(self, bug_class_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM phase_progress WHERE bug_class_id = ? ORDER BY phase",
            (bug_class_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def bump_phase_progress(
        self,
        bug_class_id: int,
        phase: str,
        resources_added: int = 0,
        notes: str | None = None,
    ) -> None:
        """Increment resources_consumed and update last_run for a phase."""
        existing = self.get_phase_progress(bug_class_id, phase)
        if existing:
            new_count = int(existing["resources_consumed"]) + resources_added
            note_update = notes if notes is not None else existing["notes"]
            self._conn.execute(
                """UPDATE phase_progress
                   SET resources_consumed = ?, last_run = ?, notes = ?
                   WHERE bug_class_id = ? AND phase = ?""",
                (new_count, _now(), note_update, bug_class_id, phase),
            )
        else:
            self._conn.execute(
                """INSERT INTO phase_progress
                   (bug_class_id, phase, resources_consumed, last_run, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (bug_class_id, phase, resources_added, _now(), notes or ""),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    def create_plan(
        self,
        bug_class_id: int,
        phase: str,
        date: str,
        target_hours: float,
        plan_dict: dict[str, Any],
        rationale: str = "",
        research_mode: str | None = None,
        status: str = "confirmed",
        tools_section: list[dict[str, str]] | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """INSERT INTO plans
               (bug_class_id, phase, research_mode, date, target_hours,
                rationale, plan_json, tools_section_json, status,
                confirmed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bug_class_id, phase, research_mode, date, target_hours,
                rationale, json.dumps(plan_dict),
                json.dumps(tools_section or []),
                status, _now(), _now(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def mark_plan_sent(self, plan_id: int) -> None:
        self._conn.execute(
            "UPDATE plans SET status = 'sent' WHERE id = ?", (plan_id,)
        )
        self._conn.commit()

    def get_plan(self, plan_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return _hydrate_plan_row(dict(row)) if row else None

    def get_latest_plan_for_bug_class(
        self, bug_class_id: int
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM plans WHERE bug_class_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (bug_class_id,),
        ).fetchone()
        return _hydrate_plan_row(dict(row)) if row else None

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(
        self,
        plan_id: int,
        bug_class_id: int,
        phase: str,
        title: str,
        description: str,
        task_type: str = "read",
        priority: str = "high",
        estimated_hours: float = 1.0,
        resource_url: str = "",
        resource_name: str = "",
        why: str = "",
        resources: list[dict[str, str]] | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """INSERT INTO tasks
               (plan_id, bug_class_id, phase, title, description, task_type,
                priority, estimated_hours, resource_url, resource_name,
                resources_json, why, status, assigned_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                plan_id, bug_class_id, phase, title, description, task_type,
                priority, estimated_hours, resource_url, resource_name,
                json.dumps(resources or []),
                why,
                _now(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return _hydrate_task_row(dict(row))

    def update_task_status(
        self,
        task_id: int,
        status: str,
        actual_hours: float | None = None,
        learnings: str = "",
    ) -> None:
        completed = _now() if status == "done" else None
        self._conn.execute(
            """UPDATE tasks
               SET status = ?, actual_hours = ?, learnings = ?, completed_date = ?
               WHERE id = ?""",
            (status, actual_hours, learnings, completed, task_id),
        )
        self._conn.commit()

    def get_tasks_for_plan(self, plan_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE plan_id = ? ORDER BY id",
            (plan_id,),
        ).fetchall()
        return [_hydrate_task_row(dict(r)) for r in rows]

    def get_pending_tasks(self, bug_class_id: int | None = None) -> list[dict[str, Any]]:
        if bug_class_id is None:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY id DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' AND bug_class_id = ? "
                "ORDER BY id DESC",
                (bug_class_id,),
            ).fetchall()
        return [_hydrate_task_row(dict(r)) for r in rows]

    def get_recent_completed_tasks(
        self, bug_class_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT * FROM tasks
               WHERE bug_class_id = ? AND status IN ('done', 'skipped')
               ORDER BY id DESC LIMIT ?""",
            (bug_class_id, limit),
        ).fetchall()
        return [_hydrate_task_row(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Consumed resources
    # ------------------------------------------------------------------

    def mark_consumed(
        self,
        bug_class_id: int,
        url: str,
        phase: str,
        title: str = "",
        source_type: str = "web",
    ) -> None:
        """Idempotent insert (INSERT OR IGNORE) for the consumed-resources ledger."""
        self._conn.execute(
            """INSERT OR IGNORE INTO consumed_resources
               (bug_class_id, url, title, phase, source_type, consumed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (bug_class_id, url, title, phase, source_type, _now()),
        )
        self._conn.commit()

    def get_consumed_urls(self, bug_class_id: int) -> set[str]:
        rows = self._conn.execute(
            "SELECT url FROM consumed_resources WHERE bug_class_id = ?",
            (bug_class_id,),
        ).fetchall()
        return {r["url"] for r in rows}

    def get_consumed_count(
        self, bug_class_id: int, phase: str | None = None
    ) -> int:
        if phase is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM consumed_resources WHERE bug_class_id = ?",
                (bug_class_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM consumed_resources "
                "WHERE bug_class_id = ? AND phase = ?",
                (bug_class_id, phase),
            ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # Feedback log
    # ------------------------------------------------------------------

    def log_feedback(
        self,
        task_id: int,
        status: str,
        actual_hours: float | None = None,
        notes: str = "",
        learnings: str = "",
        source: str = "email",
    ) -> None:
        self._conn.execute(
            """INSERT INTO feedback_log
               (task_id, status, actual_hours, notes, learnings, source, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, status, actual_hours, notes, learnings, source, _now()),
        )
        self._conn.commit()

    def get_recent_feedback(
        self, bug_class_id: int, limit: int = 15
    ) -> list[dict[str, Any]]:
        """Recent feedback entries for tasks in this bug class — joined with task title."""
        rows = self._conn.execute(
            """SELECT f.notes, f.learnings, f.actual_hours, f.received_at,
                      t.title, t.task_type, t.phase
               FROM feedback_log f
               JOIN tasks t ON f.task_id = t.id
               WHERE t.bug_class_id = ?
               ORDER BY f.received_at DESC
               LIMIT ?""",
            (bug_class_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # User notes
    # ------------------------------------------------------------------

    def append_user_note(self, note: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO user_notes (note, received_at) VALUES (?, ?)",
            (note, _now()),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def get_user_notes(self, limit: int = 15) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM user_notes ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()
