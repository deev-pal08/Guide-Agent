"""Tools available to the Guide Agent brains.

All tools are exposed as Anthropic SDK tool definitions (TOOL_DEFS) plus
corresponding Python implementations on the Tools class. The Tools class
holds shared state (config, store, skill loader, newsletter reader) so
implementations can access them.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from guide_agent.config import AppConfig
from guide_agent.skills.loader import (
    READ_SKILL_REFERENCE_TOOL_DEF,
    SkillLoader,
    SkillNotFoundError,
)
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions for the Anthropic SDK
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL_DEF = {
    "name": "web_search",
    "description": (
        "Search the web for resources related to a specific security bug class. "
        "Uses Brave + Tavily + Exa in parallel and deduplicates by URL. "
        "Batch multiple queries in a single turn for efficiency."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query — be specific about the bug class and the phase "
                    "intent, e.g. 'postMessage origin validation bypass writeup'"
                ),
            },
        },
        "required": ["query"],
    },
}

VERIFY_URL_TOOL_DEF = {
    "name": "verify_url",
    "description": (
        "Check if a URL is live and retrieve the page title. "
        "Always verify every URL before including it in the final plan. "
        "Use the returned page_title as the task title."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to verify",
            },
        },
        "required": ["url"],
    },
}

NEWSLETTER_QUERY_TOOL_DEF = {
    "name": "newsletter_query",
    "description": (
        "Search the user's Newsletter Agent SQLite database for articles "
        "relevant to a bug class. Returns articles with title, url, priority, "
        "and AI summary. Use this in learn and examples phases before web_search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Keywords to match against article titles/tags/summaries. "
                    "Include the bug class name plus synonyms and sub-areas."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max articles to return (default 25, max 50)",
            },
        },
        "required": ["keywords"],
    },
}

SEARCH_CONSUMED_TOOL_DEF = {
    "name": "search_consumed_resources",
    "description": (
        "Check whether specific URLs or titles have already been covered for "
        "the active bug class. Use this to avoid re-assigning material the "
        "user has already studied."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class_id": {
                "type": "integer",
                "description": "The bug class id to scope the lookup",
            },
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of URLs to check",
            },
        },
        "required": ["bug_class_id", "urls"],
    },
}


# All tool defs in one place — phase agents pick which they need
ALL_TOOL_DEFS = [
    WEB_SEARCH_TOOL_DEF,
    VERIFY_URL_TOOL_DEF,
    NEWSLETTER_QUERY_TOOL_DEF,
    SEARCH_CONSUMED_TOOL_DEF,
    READ_SKILL_REFERENCE_TOOL_DEF,
]


# ---------------------------------------------------------------------------
# Tools implementation
# ---------------------------------------------------------------------------


class Tools:
    """Shared tool implementations bound to config + state + skill loader."""

    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        skill_loader: SkillLoader,
    ):
        self.config = config
        self.state = state
        self.skill_loader = skill_loader

    # ------------------------------------------------------------------
    # Dispatch — called by agent loops on a tool_use block
    # ------------------------------------------------------------------

    def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            if tool_name == "web_search":
                return self.web_search(**tool_input)
            if tool_name == "verify_url":
                return self.verify_url(**tool_input)
            if tool_name == "newsletter_query":
                return self.newsletter_query(**tool_input)
            if tool_name == "search_consumed_resources":
                return self.search_consumed_resources(**tool_input)
            if tool_name == "read_skill_reference":
                return self.read_skill_reference(**tool_input)
            return {"error": f"Unknown tool: {tool_name}"}
        except TypeError as e:
            return {"error": f"Bad arguments for {tool_name}: {e}"}
        except Exception as e:
            logger.exception("Tool %s raised", tool_name)
            return {"error": f"Tool {tool_name} failed: {e}"}

    # ------------------------------------------------------------------
    # web_search — multi-source parallel
    # ------------------------------------------------------------------

    def web_search(self, query: str) -> dict[str, Any]:
        if not self.config.search.enabled:
            return {"error": "Web search is disabled"}

        max_results = self.config.search.max_results
        providers: dict[str, Any] = {}

        if self.config.search.brave.enabled and self.config.search.brave.api_key:
            providers["brave"] = lambda q=query: self._search_brave(q, max_results)
        if self.config.search.tavily.enabled and self.config.search.tavily.api_key:
            providers["tavily"] = lambda q=query: self._search_tavily(q, max_results)
        if self.config.search.exa.enabled and self.config.search.exa.api_key:
            providers["exa"] = lambda q=query: self._search_exa(q, max_results)

        if not providers:
            return {"error": "No search providers configured"}

        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fn): name for name, fn in providers.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results = future.result()
                    for r in results:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append(r)
                except Exception as e:
                    errors.append(f"{name}: {e}")

        output: dict[str, Any] = {
            "query": query,
            "results": all_results[: max_results * 2],
        }
        if errors:
            output["provider_errors"] = errors
        return output

    def _search_brave(self, query: str, max_results: int) -> list[dict[str, Any]]:
        api_key = self.config.search.brave.api_key
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": (r.get("description", "") or "")[:120],
                "source": "brave",
            }
            for r in data.get("web", {}).get("results", [])[:max_results]
        ]

    def _search_tavily(self, query: str, max_results: int) -> list[dict[str, Any]]:
        api_key = self.config.search.tavily.api_key
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "api_key": api_key,
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": (r.get("content", "") or "")[:120],
                "source": "tavily",
            }
            for r in data.get("results", [])[:max_results]
        ]

    def _search_exa(self, query: str, max_results: int) -> list[dict[str, Any]]:
        api_key = self.config.search.exa.api_key
        resp = httpx.post(
            "https://api.exa.ai/search",
            json={
                "query": query,
                "numResults": max_results,
                "type": "neural",
                "useAutoprompt": True,
            },
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": "",
                "source": "exa",
            }
            for r in data.get("results", [])[:max_results]
        ]

    # ------------------------------------------------------------------
    # verify_url
    # ------------------------------------------------------------------

    def verify_url(self, url: str) -> dict[str, Any]:
        try:
            with httpx.Client(follow_redirects=True, timeout=10) as client:
                r = client.get(url)
                result: dict[str, Any] = {
                    "url": url,
                    "live": r.status_code < 400,
                    "status_code": r.status_code,
                    "final_url": str(r.url),
                }
                if r.status_code < 400:
                    match = re.search(
                        r"<title[^>]*>([^<]+)</title>",
                        r.text[:10000],
                        re.IGNORECASE,
                    )
                    if match:
                        result["page_title"] = match.group(1).strip()
                return result
        except Exception as e:
            return {"url": url, "live": False, "error": str(e)}

    # ------------------------------------------------------------------
    # newsletter_query
    # ------------------------------------------------------------------

    def newsletter_query(
        self,
        keywords: list[str],
        limit: int = 25,
    ) -> dict[str, Any]:
        if not self.config.newsletter.enabled or not self.config.newsletter.project_dir:
            return {"error": "Newsletter integration disabled in config"}

        from guide_agent.sources.newsletter import NewsletterReader

        limit = min(max(1, limit), 50)
        try:
            reader = NewsletterReader(self.config.newsletter.project_dir)
        except FileNotFoundError as e:
            return {"error": f"Newsletter DB not found: {e}"}

        if not reader.is_available():
            return {"error": "Newsletter DB unavailable"}

        try:
            results = reader.search_articles(keywords, limit=limit)
        finally:
            reader.close()

        return {
            "keywords": keywords,
            "count": len(results),
            "articles": results,
        }

    # ------------------------------------------------------------------
    # search_consumed_resources
    # ------------------------------------------------------------------

    def search_consumed_resources(
        self,
        bug_class_id: int,
        urls: list[str],
    ) -> dict[str, Any]:
        consumed = self.state.get_consumed_urls(bug_class_id)
        hits = [u for u in urls if u in consumed]
        return {
            "bug_class_id": bug_class_id,
            "consumed": hits,
            "not_consumed": [u for u in urls if u not in consumed],
            "total_consumed_for_class": len(consumed),
        }

    # ------------------------------------------------------------------
    # read_skill_reference (progressive disclosure level 3)
    # ------------------------------------------------------------------

    def read_skill_reference(self, skill_name: str, filename: str) -> dict[str, Any]:
        try:
            content = self.skill_loader.read_reference(skill_name, filename)
        except SkillNotFoundError as e:
            return {"error": str(e)}
        except ValueError as e:
            return {"error": str(e)}
        return {
            "skill_name": skill_name,
            "filename": filename,
            "content": content,
        }


# ---------------------------------------------------------------------------
# JSON helper for serialising tool results into Anthropic tool_result blocks
# ---------------------------------------------------------------------------


def serialize_tool_result(result: dict[str, Any]) -> str:
    """Serialise a tool result dict to JSON for the SDK content block."""
    return json.dumps(result, ensure_ascii=False, default=str)
