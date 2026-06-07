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
    """
    CREATE TABLE IF NOT EXISTS prefetched_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        fetched_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_prefetched_source
        ON prefetched_resources(source)
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_tags (
        resource_id INTEGER NOT NULL REFERENCES prefetched_resources(id)
            ON DELETE CASCADE,
        bug_class TEXT NOT NULL,
        tagged_at TIMESTAMP NOT NULL,
        PRIMARY KEY (resource_id, bug_class)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_tags_class
        ON resource_tags(bug_class)
    """,
    """
    CREATE TABLE IF NOT EXISTS bug_class_tag_scans (
        bug_class TEXT PRIMARY KEY,
        last_scanned_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bug_class_expansions (
        bug_class TEXT PRIMARY KEY,
        terms_json TEXT NOT NULL,
        expanded_at TIMESTAMP NOT NULL
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

    # ------------------------------------------------------------------
    # Prefetched resources + lazy bug-class tagging
    # ------------------------------------------------------------------

    def bulk_upsert_prefetched(
        self,
        source: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Insert/update prefetched resources for a source.

        Each row needs: url. Optional: title, summary, metadata (dict).
        Returns {"inserted": N, "updated": N, "total": N}.

        When a URL is updated, all its tags are deleted so the next query
        for that bug class will re-scan and re-tag.
        """
        inserted = 0
        updated = 0
        for r in rows:
            url = (r.get("url") or "").strip()
            if not url:
                continue
            title = (r.get("title") or "").strip()
            summary = (r.get("summary") or "").strip()
            metadata = r.get("metadata") or {}
            now = _now()

            existing = self._conn.execute(
                "SELECT id FROM prefetched_resources WHERE url = ?", (url,),
            ).fetchone()
            if existing:
                rid = int(existing["id"])
                self._conn.execute(
                    """UPDATE prefetched_resources
                       SET source = ?, title = ?, summary = ?,
                           metadata_json = ?, fetched_at = ?
                       WHERE id = ?""",
                    (source, title, summary, json.dumps(metadata), now, rid),
                )
                # Clear tags so next query re-scans against new title/summary
                self._conn.execute(
                    "DELETE FROM resource_tags WHERE resource_id = ?", (rid,),
                )
                updated += 1
            else:
                self._conn.execute(
                    """INSERT INTO prefetched_resources
                       (source, url, title, summary, metadata_json, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source, url, title, summary, json.dumps(metadata), now),
                )
                inserted += 1
        # When any new rows were added, invalidate the per-class scan
        # markers so the next query re-scans (the new rows haven't been
        # tagged yet). Same for updates that cleared tags.
        if inserted or updated:
            self._conn.execute("DELETE FROM bug_class_tag_scans")
        self._conn.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "total": inserted + updated,
        }

    def get_prefetched_count(self, source: str | None = None) -> int:
        if source is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM prefetched_resources",
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM prefetched_resources WHERE source = ?",
                (source,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def _ensure_bug_class_tagged(self, bug_class: str) -> None:
        """First call for a bug class scans all prefetched rows + writes tags.

        Subsequent calls are no-ops until the scan marker is cleared by a
        refresh (`bulk_upsert_prefetched` wipes it when anything changes).
        """
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return

        already = self._conn.execute(
            "SELECT last_scanned_at FROM bug_class_tag_scans WHERE bug_class = ?",
            (bc_norm,),
        ).fetchone()
        if already:
            return

        # Support '|'-separated synonyms — tag a resource if ANY needle matches.
        needles = [n.strip() for n in bc_norm.split("|") if n.strip()]
        if not needles:
            return

        # Build the WHERE clause: OR of LOWER(title || summary) LIKE %needle%
        where_clauses = []
        params: list[Any] = []
        for needle in needles:
            where_clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ?)",
            )
            like = f"%{needle}%"
            params.extend([like, like])

        sql = (
            "SELECT id FROM prefetched_resources WHERE "
            + " OR ".join(where_clauses)
        )
        matched = self._conn.execute(sql, params).fetchall()
        now = _now()
        for row in matched:
            self._conn.execute(
                """INSERT OR IGNORE INTO resource_tags
                   (resource_id, bug_class, tagged_at) VALUES (?, ?, ?)""",
                (int(row["id"]), bc_norm, now),
            )
        self._conn.execute(
            """INSERT OR REPLACE INTO bug_class_tag_scans
               (bug_class, last_scanned_at) VALUES (?, ?)""",
            (bc_norm, now),
        )
        self._conn.commit()

    def query_prefetched(
        self,
        bug_class: str,
        bug_class_id: int | None = None,
        source: str | None = None,
        exclude_urls: list[str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Return prefetched resources tagged for this bug class.

        Resources are tagged with the bug class at INSERT time (by
        add_resources_for_bug_class), so this is a pure indexed JOIN —
        no scanning, no lazy tagging.

        Excludes URLs already in `consumed_resources` for the given
        bug_class_id (if provided).
        """
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return {"error": "bug_class is required"}

        limit = min(max(1, int(limit)), 200)
        exclude_set: set[str] = set()
        if exclude_urls:
            exclude_set = {str(u).strip() for u in exclude_urls if str(u).strip()}
        if bug_class_id is not None:
            exclude_set |= self.get_consumed_urls(bug_class_id)

        params: list[Any] = [bc_norm]
        sql = (
            "SELECT r.id, r.source, r.url, r.title, r.summary, "
            "r.metadata_json, r.fetched_at "
            "FROM prefetched_resources r "
            "JOIN resource_tags t ON t.resource_id = r.id "
            "WHERE t.bug_class = ? "
        )
        if source:
            sql += "AND r.source = ? "
            params.append(source)
        sql += "ORDER BY r.fetched_at DESC"

        rows = self._conn.execute(sql, params).fetchall()
        total_tagged = len(rows)
        excluded = 0
        results: list[dict[str, Any]] = []
        for row in rows:
            if row["url"] in exclude_set:
                excluded += 1
                continue
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            results.append({
                "url": row["url"],
                "title": row["title"],
                "summary": row["summary"],
                "source": row["source"],
                "fetched_at": row["fetched_at"],
                "metadata": metadata,
            })
            if len(results) >= limit:
                break

        return {
            "bug_class": bc_norm,
            "source_filter": source,
            "total_tagged": total_tagged,
            "excluded_count": excluded,
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # Per-class scoped resource ingest (the new model)
    # ------------------------------------------------------------------

    def add_resources_for_bug_class(
        self,
        source: str,
        bug_class: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Insert resources AND tag each one with the given bug class.

        This is the primary write path for per-class fan-out fetches.
        Resources are NOT scanned across other bug classes — the tag is
        applied because the caller said "I fetched these specifically
        for bug_class X".

        Idempotent: re-running with the same rows is a no-op (UNIQUE
        on url + UNIQUE on resource_tags).
        """
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return {"inserted": 0, "tagged": 0, "skipped": 0}

        inserted = 0
        tagged = 0
        skipped = 0
        now = _now()

        for r in rows:
            url = (r.get("url") or "").strip()
            if not url:
                skipped += 1
                continue
            title = (r.get("title") or "").strip()
            summary = (r.get("summary") or "").strip()
            metadata = r.get("metadata") or {}

            existing = self._conn.execute(
                "SELECT id FROM prefetched_resources WHERE url = ?", (url,),
            ).fetchone()
            if existing:
                rid = int(existing["id"])
                # Update metadata if title/summary improved (don't blast existing)
                if title or summary:
                    self._conn.execute(
                        """UPDATE prefetched_resources
                           SET title = COALESCE(NULLIF(?, ''), title),
                               summary = COALESCE(NULLIF(?, ''), summary),
                               metadata_json = ?,
                               fetched_at = ?
                           WHERE id = ?""",
                        (title, summary, json.dumps(metadata), now, rid),
                    )
            else:
                cur = self._conn.execute(
                    """INSERT INTO prefetched_resources
                       (source, url, title, summary, metadata_json, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source, url, title, summary, json.dumps(metadata), now),
                )
                rid = int(cur.lastrowid or 0)
                inserted += 1

            # Tag with bug class — ignore if already tagged
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO resource_tags
                   (resource_id, bug_class, tagged_at) VALUES (?, ?, ?)""",
                (rid, bc_norm, now),
            )
            if cur.rowcount > 0:
                tagged += 1

        self._conn.commit()
        return {
            "inserted": inserted,
            "tagged": tagged,
            "skipped": skipped,
            "total": len(rows),
        }

    def unread_count_for_bug_class(
        self,
        bug_class: str,
        bug_class_id: int,
    ) -> int:
        """Count tagged resources NOT in consumed_resources for this class."""
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return 0
        row = self._conn.execute(
            """SELECT COUNT(*) AS c
               FROM prefetched_resources r
               JOIN resource_tags t ON t.resource_id = r.id
               WHERE t.bug_class = ?
                 AND r.url NOT IN (
                     SELECT url FROM consumed_resources WHERE bug_class_id = ?
                 )""",
            (bc_norm, bug_class_id),
        ).fetchone()
        return int(row["c"]) if row else 0

    def tagged_count_for_bug_class(self, bug_class: str) -> int:
        """Total resources tagged for this class (read + unread)."""
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM resource_tags WHERE bug_class = ?",
            (bc_norm,),
        ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # Bug-class expansion cache (Lever 3 — LLM-generated synonym set)
    # ------------------------------------------------------------------

    def get_expansion(self, bug_class: str) -> list[str] | None:
        """Fetch the cached synonym list for this bug class, or None."""
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return None
        row = self._conn.execute(
            "SELECT terms_json FROM bug_class_expansions WHERE bug_class = ?",
            (bc_norm,),
        ).fetchone()
        if not row:
            return None
        try:
            terms = json.loads(row["terms_json"])
            return terms if isinstance(terms, list) else None
        except json.JSONDecodeError:
            return None

    def set_expansion(self, bug_class: str, terms: list[str]) -> None:
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return
        # Dedupe (case-insensitive), keep first-seen ordering, then ensure
        # the canonical class name is first regardless of input order.
        seen: set[str] = set()
        ordered: list[str] = []
        for t in terms:
            if not isinstance(t, str):
                continue
            tn = t.strip().lower()
            if not tn or tn in seen:
                continue
            seen.add(tn)
            ordered.append(tn)
        if bc_norm in ordered:
            ordered.remove(bc_norm)
        ordered.insert(0, bc_norm)
        self._conn.execute(
            """INSERT OR REPLACE INTO bug_class_expansions
               (bug_class, terms_json, expanded_at) VALUES (?, ?, ?)""",
            (bc_norm, json.dumps(ordered), _now()),
        )
        self._conn.commit()

    def delete_expansion(self, bug_class: str) -> None:
        bc_norm = bug_class.strip().lower()
        if not bc_norm:
            return
        self._conn.execute(
            "DELETE FROM bug_class_expansions WHERE bug_class = ?", (bc_norm,),
        )
        self._conn.commit()


