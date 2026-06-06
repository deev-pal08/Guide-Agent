"""Read-only access to the Newsletter Agent's SQLite article database.

Adapted from the Planner Agent's newsletter reader but with a different
query shape — we don't pull by priority tier, we keyword-search for articles
relevant to a single bug class.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


PRIORITY_SHORT = {
    "CRITICAL - ACT NOW": "CRITICAL",
    "IMPORTANT - READ THIS WEEK": "IMPORTANT",
    "INTERESTING - QUEUE FOR WEEKEND": "INTERESTING",
    "REFERENCE - SAVE FOR LATER": "REFERENCE",
}


class NewsletterReader:
    """Read-only access to the Newsletter Agent's article database."""

    def __init__(self, project_dir: str):
        expanded = os.path.expanduser(project_dir)
        self.db_path = Path(expanded) / "data" / "newsletter.db"
        self._conn: sqlite3.Connection | None = None

        if not self.db_path.exists():
            raise FileNotFoundError(f"Newsletter DB not found at {self.db_path}")

        try:
            self._conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True,
            )
            self._conn.row_factory = sqlite3.Row
        except (sqlite3.OperationalError, PermissionError) as e:
            logger.warning("Cannot open newsletter DB at %s: %s", self.db_path, e)
            self._conn = None

    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._conn is not None

    def get_db_age_days(self) -> float | None:
        if not self._conn:
            return None
        try:
            mtime = os.path.getmtime(self.db_path)
        except (OSError, PermissionError):
            return None
        return (datetime.now(UTC).timestamp() - mtime) / 86400

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Keyword search across all digest articles
    # ------------------------------------------------------------------

    def search_articles(
        self,
        keywords: list[str],
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return articles whose title/tags/summary matches ANY keyword.

        Loads all digest articles from the digests.articles_json column,
        deduplicates by URL, and scores each by number of keyword hits across
        title (×3 weight), tags (×2), and ai_summary (×1). Returns top N.
        """
        if not self._conn:
            return []

        articles = self._load_all_articles()
        keywords_lower = [k.lower() for k in keywords if k.strip()]
        if not keywords_lower:
            return []

        scored: list[tuple[int, dict[str, Any]]] = []
        for art in articles:
            score = self._score(art, keywords_lower)
            if score > 0:
                scored.append((score, art))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [self._project_article(a, s) for s, a in scored[:limit]]

    def _score(self, article: dict[str, Any], keywords: list[str]) -> int:
        title = (article.get("title", "") or "").lower()
        summary = (article.get("ai_summary", "") or "").lower()
        tags = [str(t).lower() for t in article.get("tags", [])] if isinstance(
            article.get("tags"), list,
        ) else []
        tag_blob = " ".join(tags)

        score = 0
        for kw in keywords:
            if kw in title:
                score += 3
            if kw in tag_blob:
                score += 2
            if kw in summary:
                score += 1
        return score

    def _project_article(self, art: dict[str, Any], score: int) -> dict[str, Any]:
        raw_priority = art.get("priority", "REFERENCE - SAVE FOR LATER")
        return {
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source_name": art.get("source_name", ""),
            "priority": PRIORITY_SHORT.get(raw_priority, "REFERENCE"),
            "tags": art.get("tags", []),
            "ai_summary": (art.get("ai_summary", "") or "")[:200],
            "published_at": art.get("published_at", ""),
            "match_score": score,
        }

    # ------------------------------------------------------------------
    # Internal: load all articles across all digests, deduped by URL
    # ------------------------------------------------------------------

    def _load_all_articles(self) -> list[dict[str, Any]]:
        if not self._conn:
            return []
        rows = self._conn.execute(
            "SELECT articles_json FROM digests WHERE articles_json IS NOT NULL",
        ).fetchall()

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                batch = json.loads(row["articles_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(batch, list):
                continue
            for art in batch:
                url = art.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    out.append(art)
        return out
