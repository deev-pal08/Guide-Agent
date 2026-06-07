"""Tools available to the Guide Agent brains.

All tools are exposed as Anthropic SDK tool definitions (TOOL_DEFS) plus
corresponding Python implementations on the Tools class. The Tools class
holds shared state (config, store, skill loader, newsletter reader) so
implementations can access them.
"""

from __future__ import annotations

import json
import logging
import os
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

CTFTIME_EVENTS_TOOL_DEF = {
    "name": "ctftime_events",
    "description": (
        "List upcoming + ongoing CTF events from CTFtime's public API. "
        "Use in the execute phase Task 3 (active CTFs / hackathons / "
        "competitions). Returns events with title, start/finish dates, "
        "format (Jeopardy / Attack-Defense), restrictions (Open / "
        "students-only), CTFtime weight (quality score), URL. Bug class "
        "is NOT a filter — CTFs accept all bugs. Filter the response by "
        "format preference, weight floor, or date window. "
        "Note: CTFtime weight is a per-event quality score; weight >= 25 "
        "is considered notable, >= 50 is top-tier."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": (
                    "How many days into the future to look. Default 60. "
                    "Use 14 for 'starting soon', 90 for 'plan ahead'."
                ),
            },
            "min_weight": {
                "type": "number",
                "description": (
                    "Minimum CTFtime weight (quality score). Default 0 "
                    "(no filter). Use 25 for notable events, 50 for top-tier."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max events to return (default 15, max 100).",
            },
        },
        "required": [],
    },
}

GITHUB_REPOS_BY_STARS_TOOL_DEF = {
    "name": "github_repos_by_stars",
    "description": (
        "Search GitHub for the most popular open-source projects matching "
        "a query, sorted by stars descending. Uses the GitHub Search API. "
        "Use in the execute phase Task 2 (popular OSS to audit for CVEs) "
        "and the Tools Section (hunting tools). Bug class is NOT typically "
        "a filter for OSS-target discovery (use language/framework instead) "
        "but IS useful for tools-section queries like 'xss exploitation' "
        "or 'jwt cracker'. Authenticated requests (GITHUB_TOKEN env var) "
        "get 30 req/min vs 10/min unauthenticated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "GitHub search query. Examples: 'language:javascript "
                    "stars:>10000', 'topic:web-framework', 'topic:xss "
                    "topic:exploitation', 'jwt parser language:go'. "
                    "Combine with `stars:>N` for popularity floor."
                ),
            },
            "min_stars": {
                "type": "integer",
                "description": (
                    "Optional popularity floor — appends `stars:>N` to "
                    "the query. Default 0 (no filter)."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max repos to return (default 15, max 100).",
            },
        },
        "required": ["query"],
    },
}

CODEREVIEWLAB_SEARCH_TOOL_DEF = {
    "name": "codereviewlab_search",
    "description": (
        "Search Code Review Lab's challenge catalog — 205 secure-code-review "
        "challenges across PHP, JavaScript/TypeScript, Go, Ruby, Python, "
        "Java, Solidity, Kotlin, Swift, fully tagged by vulnerability type "
        "(XSS, RCE, SSRF, CSRF, JWT, Injection, etc.) and difficulty. "
        "Each result has a direct challenge URL + language + difficulty + "
        "exploit + mitigation explanation. Use in the practice phase for "
        "code review training — complements PortSwigger Labs (which test "
        "exploitation) by training the user to spot bugs in source. "
        "Fetches the entire catalog in one API call and caches it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class to filter by. Substring-matched against the "
                    "challenge's vulnType field. Use '|' for OR. Examples: "
                    "'xss', 'ssrf', 'jwt', 'csrf', 'injection|rce', "
                    "'authorization|access control'."
                ),
            },
            "language": {
                "type": "string",
                "description": (
                    "Optional language filter — e.g. 'PHP', 'JavaScript', "
                    "'Go', 'Solidity'. Case-insensitive substring match."
                ),
            },
            "difficulty": {
                "type": "string",
                "enum": ["EASY", "MEDIUM", "HARD"],
                "description": "Optional difficulty filter.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 15, max 100).",
            },
        },
        "required": ["bug_class"],
    },
}

PREFETCHED_RESOURCE_SEARCH_TOOL_DEF = {
    "name": "prefetched_resource_search",
    "description": (
        "Search the LOCAL prefetched_resources DB for the active bug class. "
        "CALL THIS FIRST in every examples-phase run before reaching for "
        "live tools — it's instant (SQLite) and returns the same shape as "
        "the live fetchers (pentesterland, blog feeds, sitemaps, reddelexc "
        "archive) but without any network calls. "
        "Resources already in the user's consumed_resources ledger are "
        "automatically excluded. Use '|' to OR synonyms in bug_class "
        "('postmessage|cross-window'). "
        "ONLY fall back to live tools (pentesterland_search, "
        "blog_feed_search, sitemap_search, hackerone_hacktivity_search) if "
        "returned_count is too low for the user's target_hours, OR the user "
        "context contains 'FRESH_FETCH=true' (--fresh CLI flag)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class to search for. Substring-matched against "
                    "title + summary at first call, then cached as a tag "
                    "for instant subsequent lookups. Examples: 'xss', "
                    "'postmessage', 'ssrf'. '|' for OR."
                ),
            },
            "bug_class_id": {
                "type": "integer",
                "description": (
                    "Numeric bug_class id. Required for consumed-resources "
                    "exclusion. Provided in the user context block."
                ),
            },
            "source": {
                "type": "string",
                "description": (
                    "Optional source filter — e.g. 'pentesterland', "
                    "'feed:Orange Tsai's Blog', 'sitemap:Sonar Research Blog', "
                    "'reddelexc'. Omit to search across all sources."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 25, max 200).",
            },
        },
        "required": ["bug_class"],
    },
}

CTFSEARCH_SEARCH_TOOL_DEF = {
    "name": "ctfsearch_search",
    "description": (
        "Search the CTFsearch (HackMap) writeup index — 35,800+ CTF "
        "writeups indexed in Typesense, queryable via a public search-only "
        "key. CTF writeups often have MORE technical depth than terse "
        "bug-bounty reports (full exploitation chains, step-by-step "
        "payloads). Covers TryHackMe / HackTheBox / OffSec / general CTF "
        "writeups. Use in the examples phase ALONGSIDE pentesterland_search "
        "and hackerone_hacktivity_search — they cover different universes "
        "(real-world disclosed reports vs CTF walkthroughs). Sorted by "
        "date desc (newest first)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class query — full-text matched against writeup "
                    "titles AND content. Examples: 'xss', 'ssrf', "
                    "'postmessage', 'jwt', 'lfi', 'sql injection'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 15, max 100).",
            },
        },
        "required": ["bug_class"],
    },
}

SITEMAP_SEARCH_TOOL_DEF = {
    "name": "sitemap_search",
    "description": (
        "Search a site's sitemap.xml for URLs matching a bug class. Use for "
        "sites that have no RSS/Atom feed but expose a sitemap (e.g. Sonar "
        "Research Blog: 538 posts in sitemap vs 10 via Brave site: search). "
        "Matches the bug class as a case-insensitive substring against the "
        "URL slug — lossy but high-yield since most security blogs put the "
        "bug class name directly in the post URL. Handles sitemap indexes "
        "(walks sub-sitemaps automatically). Use '|' to OR synonyms."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sitemap_url": {
                "type": "string",
                "description": (
                    "Full sitemap URL. Common paths: /sitemap.xml, "
                    "/sitemap_index.xml. Example: "
                    "https://www.sonarsource.com/sitemap.xml"
                ),
            },
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class to substring-match against URL slugs "
                    "(case-insensitive). Use '|' for OR matching, e.g. "
                    "'xss|cross-site' or 'rce|code-execution|remote-code'."
                ),
            },
            "url_prefix": {
                "type": "string",
                "description": (
                    "Optional URL prefix filter — only return URLs starting "
                    "with this string. Use to scope to a blog section: "
                    "'https://www.sonarsource.com/blog/' drops product pages, "
                    "translated mirrors, etc."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 15, max 100).",
            },
        },
        "required": ["sitemap_url", "bug_class"],
    },
}

BLOG_FEED_SEARCH_TOOL_DEF = {
    "description": (
        "Search a security-research blog's RSS/Atom feed for posts matching a "
        "bug class. Brave's `site:` search caps at ~10 results — most "
        "blogs have far more (Orange Tsai = 100, Embrace The Red = 224, "
        "PentesterLab = 186, etc.). This tool fetches the blog's feed XML "
        "(common paths: /atom.xml, /index.xml, /feed.xml, /rss) and "
        "substring-matches the bug class against entry titles + summaries. "
        "USE this in the examples phase whenever a hardcoded source is a "
        "blog with a feed_url configured. Returns entries ranked by date "
        "(newest first), with title + link + summary snippet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "feed_url": {
                "type": "string",
                "description": (
                    "Full RSS or Atom feed URL. Examples: "
                    "https://blog.orange.tw/atom.xml, "
                    "https://embracethered.com/blog/index.xml, "
                    "https://portswigger.net/research/rss"
                ),
            },
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class to search for — case-insensitive substring "
                    "match against entry title + summary. Use multiple "
                    "synonyms separated by '|' for OR matching, e.g. "
                    "'postmessage|postMessage|cross-window'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 15, max 100).",
            },
        },
        "required": ["feed_url", "bug_class"],
    },
}

PENTESTERLAND_SEARCH_TOOL_DEF = {
    "name": "pentesterland_search",
    "description": (
        "Search Pentester Land's curated bug-bounty writeup database "
        "(6400+ structured entries, ~1100 XSS, ~280 SSRF, ~33 postMessage, etc.) "
        "by bug class tag. Each entry has direct external URL + title + "
        "authors + program + bug tags + bounty + dates. Far better than "
        "site:pentester.land web search — the writeup list is JS-rendered so "
        "search engines never index the individual writeup links. Use in the "
        "examples phase ALONGSIDE hackerone_hacktivity_search — that tool "
        "covers H1, this one covers Medium / personal blogs / Sonar / "
        "includesecurity / hashnode / infosecwriteups etc. Sorted by bounty "
        "amount descending."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class tag — case-insensitive substring match against "
                    "the writeup's Bugs[] array. Examples: 'xss', 'ssrf', "
                    "'postmessage', 'idor', 'rce', 'oauth', 'sql injection', "
                    "'prototype pollution', 'subdomain takeover'."
                ),
            },
            "min_bounty": {
                "type": "integer",
                "description": (
                    "Minimum bounty in USD. 0 = no filter (includes unpaid + "
                    "unknown bounty). >0 = drops entries with missing or zero "
                    "bounty. Default 0."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 15, max 200).",
            },
            "exclude_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Writeup URLs to skip (already consumed by user). "
                    "Match is exact."
                ),
            },
        },
        "required": ["bug_class"],
    },
}

HACKERONE_HACKTIVITY_SEARCH_TOOL_DEF = {
    "name": "hackerone_hacktivity_search",
    "description": (
        "Search HackerOne hacktivity (all disclosed reports) for a bug class, "
        "filtered server-side by severity and bounty range. Returns reports "
        "sorted by severity (Critical > High > Medium > Low > None) then by "
        "bounty amount descending — the highest-impact, best-paid reports "
        "come first. Use this in the examples phase WHENEVER you need real "
        "disclosed bug reports for a bug class. Far superior to "
        "site:hackerone.com/reports web search — that only returns ~10 "
        "Brave-indexed URLs, this returns the full hacktivity firehose "
        "(2000+ XSS reports, etc.) with structured severity/bounty/CWE."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bug_class": {
                "type": "string",
                "description": (
                    "Free-text bug class query — Lucene syntax allowed. "
                    "Examples: 'xss', 'postmessage', 'ssrf', "
                    "'prototype pollution', 'oauth misconfiguration'."
                ),
            },
            "min_severity": {
                "type": "string",
                "enum": ["none", "low", "medium", "high", "critical"],
                "description": (
                    "Minimum severity floor (inclusive). Defaults to 'high' "
                    "so only High + Critical reports return. Use 'medium' "
                    "for a wider net, 'critical' for the top tier only."
                ),
            },
            "min_bounty": {
                "type": "integer",
                "description": (
                    "Minimum bounty amount in USD (inclusive). 0 = no "
                    "bounty filter, 1 = paid reports only, 1000 = at "
                    "least $1k. Default 0."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 15, max 200)",
            },
            "exclude_report_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Report IDs to exclude from results (e.g. ones the user "
                    "has already drained). Pass the bare numeric ID, not the "
                    "full URL. Useful for follow-up runs on high-volume "
                    "classes (XSS has 451+ high-sev reports — drain in waves)."
                ),
            },
        },
        "required": ["bug_class"],
    },
}

GITHUB_REPO_SEARCH_TOOL_DEF = {
    "name": "github_repo_search",
    "description": (
        "Find bug-class-specific files inside a public GitHub repository "
        "by walking its file tree. Use this WHENEVER a hardcoded source "
        "URL is github.com/<owner>/<repo>, because web_search providers "
        "rarely index GitHub subdirectory READMEs. Returns ranked paths "
        "(top-level + README.md prioritized) matching the bug class name "
        "(fuzzy, case-insensitive, alphanumeric normalized). For example, "
        "calling this on PayloadsAllTheThings with bug_class='xss' returns "
        "'XSS Injection/README.md' and friends — content the agent would "
        "otherwise miss entirely."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": (
                    "Full GitHub URL — accepts both https://github.com/<owner>/<repo> "
                    "and https://github.com/<owner>/<repo>/tree/<branch> shapes"
                ),
            },
            "bug_class": {
                "type": "string",
                "description": (
                    "Bug class name to filter paths by (e.g. 'xss', "
                    "'postmessage', 'prototype pollution'). Matched via "
                    "alphanumeric-only substring comparison."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10, max 25)",
            },
        },
        "required": ["repo_url", "bug_class"],
    },
}


# All tool defs in one place — phase agents pick which they need
ALL_TOOL_DEFS = [
    WEB_SEARCH_TOOL_DEF,
    VERIFY_URL_TOOL_DEF,
    NEWSLETTER_QUERY_TOOL_DEF,
    SEARCH_CONSUMED_TOOL_DEF,
    PREFETCHED_RESOURCE_SEARCH_TOOL_DEF,
    GITHUB_REPO_SEARCH_TOOL_DEF,
    GITHUB_REPOS_BY_STARS_TOOL_DEF,
    HACKERONE_HACKTIVITY_SEARCH_TOOL_DEF,
    PENTESTERLAND_SEARCH_TOOL_DEF,
    CODEREVIEWLAB_SEARCH_TOOL_DEF,
    BLOG_FEED_SEARCH_TOOL_DEF,
    SITEMAP_SEARCH_TOOL_DEF,
    CTFSEARCH_SEARCH_TOOL_DEF,
    CTFTIME_EVENTS_TOOL_DEF,
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
            if tool_name == "github_repo_search":
                return self.github_repo_search(**tool_input)
            if tool_name == "hackerone_hacktivity_search":
                return self.hackerone_hacktivity_search(**tool_input)
            if tool_name == "pentesterland_search":
                return self.pentesterland_search(**tool_input)
            if tool_name == "blog_feed_search":
                return self.blog_feed_search(**tool_input)
            if tool_name == "sitemap_search":
                return self.sitemap_search(**tool_input)
            if tool_name == "ctfsearch_search":
                return self.ctfsearch_search(**tool_input)
            if tool_name == "codereviewlab_search":
                return self.codereviewlab_search(**tool_input)
            if tool_name == "ctftime_events":
                return self.ctftime_events(**tool_input)
            if tool_name == "github_repos_by_stars":
                return self.github_repos_by_stars(**tool_input)
            if tool_name == "prefetched_resource_search":
                return self.prefetched_resource_search(**tool_input)
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
    # github_repo_search — find bug-class-specific paths inside a repo
    # ------------------------------------------------------------------

    def github_repo_search(
        self,
        repo_url: str,
        bug_class: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Walk a public GitHub repo's tree and return paths matching the bug class.

        Uses the Git Tree API (recursive=1) — one HTTP call per repo, returns
        the whole file list. Authenticates via GITHUB_TOKEN env var if set
        (5000 req/hr vs 60 unauthenticated). Public-repo read is enough.
        """
        owner, repo = _parse_github_repo(repo_url)
        if not owner or not repo:
            return {"error": f"Not a recognizable GitHub repo URL: {repo_url!r}"}

        limit = min(max(1, limit), 25)
        normalised_query = _normalise_for_match(bug_class)
        if not normalised_query:
            return {"error": "bug_class is empty after normalization"}

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "guide-agent/0.1",
        }
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        api_url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
            f"?recursive=1"
        )

        try:
            with httpx.Client(timeout=15, headers=headers, follow_redirects=True) as client:
                resp = client.get(api_url)
        except httpx.HTTPError as e:
            return {"error": f"GitHub API request failed: {e}"}

        if resp.status_code == 404:
            return {"error": f"Repo not found or not accessible: {owner}/{repo}"}
        if resp.status_code == 403:
            return {
                "error": (
                    "GitHub API rate-limit or forbidden — set GITHUB_TOKEN "
                    "for 5000/hr instead of 60/hr."
                ),
            }
        if resp.status_code != 200:
            return {
                "error": (
                    f"GitHub API returned {resp.status_code}: "
                    f"{resp.text[:200]}"
                ),
            }

        data = resp.json()
        tree = data.get("tree", [])
        if data.get("truncated"):
            logger.warning(
                "GitHub Tree API truncated response for %s/%s (very large repo)",
                owner, repo,
            )

        # Score each path
        scored: list[tuple[int, dict[str, Any]]] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path", "")
            if not path:
                continue

            normalised_path = _normalise_for_match(path)
            if normalised_query not in normalised_path:
                continue

            score = _score_repo_path(
                path=path,
                normalised_path=normalised_path,
                normalised_query=normalised_query,
            )
            if score <= 0:
                continue

            encoded_path = path.replace(" ", "%20")
            blob_url = f"https://github.com/{owner}/{repo}/blob/HEAD/{encoded_path}"
            raw_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{encoded_path}"
            )
            scored.append((score, {
                "path": path,
                "blob_url": blob_url,
                "raw_url": raw_url,
                "score": score,
            }))

        scored.sort(key=lambda t: t[0], reverse=True)
        results = [r for _, r in scored[:limit]]

        return {
            "repo": f"{owner}/{repo}",
            "bug_class": bug_class,
            "matched_count": len(scored),
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # hackerone_hacktivity_search — full hacktivity firehose via GraphQL
    # ------------------------------------------------------------------

    def hackerone_hacktivity_search(
        self,
        bug_class: str,
        min_severity: str = "high",
        min_bounty: int = 0,
        limit: int = 15,
        exclude_report_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query HackerOne's unauthenticated hacktivity GraphQL search.

        Filters server-side via Lucene query_string (severity_rating,
        total_awarded_amount). Sorts client-side by severity rank then
        bounty descending so the best reports appear first.
        """
        bug_class = (bug_class or "").strip()
        if not bug_class:
            return {"error": "bug_class is required"}

        min_severity_norm = (min_severity or "high").lower().strip()
        if min_severity_norm not in _SEVERITY_RANK:
            return {
                "error": (
                    f"min_severity must be one of "
                    f"{sorted(_SEVERITY_RANK.keys())}, got {min_severity!r}"
                ),
            }

        try:
            min_bounty = max(0, int(min_bounty))
        except (TypeError, ValueError):
            return {"error": f"min_bounty must be an integer, got {min_bounty!r}"}

        limit = min(max(1, int(limit)), 200)
        exclude_set = {str(x).strip() for x in (exclude_report_ids or []) if str(x).strip()}

        lucene_query = _build_hacktivity_lucene(
            bug_class=bug_class,
            min_severity=min_severity_norm,
            min_bounty=min_bounty,
        )

        # Page through results until we have `limit` items or hit the cap.
        # GraphQL caps `size` at 100; pull bigger pages for big limits.
        page_size = min(100, max(limit * 2, 25))
        # Enough pages to cover the cap (limit=200, page=100 -> 2 pages min).
        # Triple it so high-volume classes with lots of dupes can still drain.
        max_pages = max(6, (limit * 3) // page_size + 1)
        all_nodes: list[dict[str, Any]] = []
        total_count = 0
        for page in range(max_pages):
            payload = {
                "query": (
                    "query($q: QueryInput!, $sort: SortInput!, "
                    "$size: Int!, $from: Int!) { "
                    "search(index: CompleteHacktivityReportIndex, "
                    "query: $q, size: $size, from: $from, sort: $sort) "
                    "{ total_count nodes { ... on HacktivityDocument "
                    "{ _id votes total_awarded_amount severity_rating "
                    "cwe submitted_at industry currency "
                    "report { title } team { handle } } } } }"
                ),
                "variables": {
                    "q": {"bool": {"must": [{"query_string": {"query": lucene_query}}]}},
                    "sort": {
                        "field": "latest_disclosable_activity_at",
                        "direction": "DESC",
                    },
                    "size": page_size,
                    "from": page * page_size,
                },
            }
            try:
                with httpx.Client(timeout=15) as client:
                    resp = client.post(
                        "https://hackerone.com/graphql",
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "guide-agent/0.1",
                            "Origin": "https://hackerone.com",
                            "Referer": "https://hackerone.com/hacktivity",
                        },
                    )
            except httpx.HTTPError as e:
                return {"error": f"HackerOne GraphQL request failed: {e}"}

            if resp.status_code != 200:
                return {
                    "error": (
                        f"HackerOne GraphQL returned {resp.status_code}: "
                        f"{resp.text[:200]}"
                    ),
                }

            body = resp.json()
            if body.get("errors"):
                return {
                    "error": "HackerOne GraphQL errors",
                    "graphql_errors": body["errors"],
                    "lucene_query": lucene_query,
                }

            search = (body.get("data") or {}).get("search") or {}
            total_count = search.get("total_count") or 0
            nodes = search.get("nodes") or []
            all_nodes.extend(nodes)

            if len(all_nodes) >= total_count or not nodes or len(all_nodes) >= limit * 3:
                break

        excluded_count = 0
        if exclude_set:
            before = len(all_nodes)
            all_nodes = [
                n for n in all_nodes
                if str(n.get("_id") or "") not in exclude_set
            ]
            excluded_count = before - len(all_nodes)

        # Sort by severity rank then bounty descending
        all_nodes.sort(
            key=lambda n: (
                _SEVERITY_RANK.get((n.get("severity_rating") or "").lower(), 0),
                n.get("total_awarded_amount") or 0,
            ),
            reverse=True,
        )

        results = []
        for n in all_nodes[:limit]:
            rid = n.get("_id")
            report = n.get("report") or {}
            team = n.get("team") or {}
            results.append({
                "url": f"https://hackerone.com/reports/{rid}",
                "report_id": rid,
                "title": report.get("title"),
                "team_handle": team.get("handle"),
                "severity": n.get("severity_rating"),
                "bounty": n.get("total_awarded_amount") or 0,
                "currency": n.get("currency") or "USD",
                "cwe": n.get("cwe"),
                "votes": n.get("votes") or 0,
                "submitted_at": n.get("submitted_at"),
                "industry": n.get("industry"),
            })

        return {
            "bug_class": bug_class,
            "min_severity": min_severity_norm,
            "min_bounty": min_bounty,
            "lucene_query": lucene_query,
            "total_count": total_count,
            "excluded_count": excluded_count,
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # pentesterland_search — 6.4k structured writeups from JSON
    # ------------------------------------------------------------------

    def pentesterland_search(
        self,
        bug_class: str,
        min_bounty: int = 0,
        limit: int = 15,
        exclude_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search Pentester Land's writeups.json by bug-class tag.

        Caches the JSON in-process (it's 3.6 MB, ~6400 entries) so multiple
        calls in the same agent run share one download.
        """
        bug_class = (bug_class or "").strip().lower()
        if not bug_class:
            return {"error": "bug_class is required"}

        try:
            min_bounty = max(0, int(min_bounty))
        except (TypeError, ValueError):
            return {"error": f"min_bounty must be an integer, got {min_bounty!r}"}

        limit = min(max(1, int(limit)), 200)
        exclude_set = {str(x).strip() for x in (exclude_urls or []) if str(x).strip()}

        try:
            entries = _load_pentesterland_writeups()
        except Exception as e:
            return {"error": f"Failed to load Pentester Land writeups: {e}"}

        matches: list[tuple[int, dict[str, Any]]] = []
        for entry in entries:
            bugs = [str(b).lower() for b in (entry.get("Bugs") or [])]
            if not any(bug_class in b for b in bugs):
                continue

            links = entry.get("Links") or []
            if not links:
                continue
            link = links[0]
            url = (link.get("Link") or "").strip()
            if not url or url in exclude_set:
                continue

            bounty_int = _parse_bounty_amount(entry.get("Bounty"))
            if min_bounty > 0 and bounty_int < min_bounty:
                continue

            matches.append((bounty_int, {
                "url": url,
                "title": link.get("Title", "").strip(),
                "authors": entry.get("Authors") or [],
                "programs": entry.get("Programs") or [],
                "bugs": entry.get("Bugs") or [],
                "bounty": bounty_int,
                "bounty_raw": entry.get("Bounty"),
                "publication_date": entry.get("PublicationDate"),
                "added_date": entry.get("AddedDate"),
            }))

        # Sort by bounty desc, then by publication_date desc as tiebreaker
        matches.sort(
            key=lambda t: (t[0], t[1].get("publication_date") or ""),
            reverse=True,
        )
        results = [m for _, m in matches[:limit]]

        return {
            "bug_class": bug_class,
            "min_bounty": min_bounty,
            "total_count": len(matches),
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # blog_feed_search — generic RSS/Atom feed substring matcher
    # ------------------------------------------------------------------

    def blog_feed_search(
        self,
        feed_url: str,
        bug_class: str,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Fetch an RSS/Atom feed and substring-match bug_class against entries.

        Caches the parsed feed per URL for the process lifetime — multiple
        calls to the same feed in one agent run share one download.
        """
        feed_url = (feed_url or "").strip()
        if not feed_url:
            return {"error": "feed_url is required"}
        if not feed_url.lower().startswith(("http://", "https://")):
            return {"error": f"feed_url must be http(s), got {feed_url!r}"}

        bug_class = (bug_class or "").strip().lower()
        if not bug_class:
            return {"error": "bug_class is required"}

        # Support '|'-separated synonyms ("postmessage|cross-window")
        needles = [s.strip() for s in bug_class.split("|") if s.strip()]
        if not needles:
            return {"error": "bug_class produced no search terms"}

        limit = min(max(1, int(limit)), 100)

        try:
            entries = _load_blog_feed_entries(feed_url)
        except Exception as e:
            return {"error": f"Failed to load feed {feed_url}: {e}"}

        matches: list[dict[str, Any]] = []
        for entry in entries:
            haystack = " ".join([
                entry.get("title") or "",
                entry.get("summary") or "",
            ]).lower()
            if not any(n in haystack for n in needles):
                continue
            matches.append(entry)

        # Feed parser already returned newest-first; slice and trim summaries.
        results: list[dict[str, Any]] = []
        for m in matches[:limit]:
            results.append({
                "url": m.get("link"),
                "title": m.get("title"),
                "published": m.get("published"),
                "summary": (m.get("summary") or "")[:300],
            })

        return {
            "feed_url": feed_url,
            "bug_class": bug_class,
            "total_in_feed": len(entries),
            "total_count": len(matches),
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # sitemap_search — substring-match URLs in a site's sitemap.xml
    # ------------------------------------------------------------------

    def sitemap_search(
        self,
        sitemap_url: str,
        bug_class: str,
        url_prefix: str | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Fetch a sitemap (or sitemap index) and substring-match URLs."""
        sitemap_url = (sitemap_url or "").strip()
        if not sitemap_url:
            return {"error": "sitemap_url is required"}
        if not sitemap_url.lower().startswith(("http://", "https://")):
            return {"error": f"sitemap_url must be http(s), got {sitemap_url!r}"}

        bug_class = (bug_class or "").strip().lower()
        if not bug_class:
            return {"error": "bug_class is required"}

        needles = [s.strip() for s in bug_class.split("|") if s.strip()]
        if not needles:
            return {"error": "bug_class produced no search terms"}

        limit = min(max(1, int(limit)), 100)
        prefix = (url_prefix or "").strip()

        try:
            urls = _load_sitemap_urls(sitemap_url)
        except Exception as e:
            return {"error": f"Failed to load sitemap {sitemap_url}: {e}"}

        if prefix:
            urls = [u for u in urls if u.startswith(prefix)]

        # Match against the URL path only (excluding scheme + host) so a
        # bug class like 'rce' doesn't false-positive on host names like
        # 'sonarsource' (contains 'rce'). Path-only also avoids matching
        # query strings and fragments.
        from urllib.parse import urlparse

        def _path_lower(u: str) -> str:
            try:
                return urlparse(u).path.lower()
            except Exception:
                return u.lower()

        matches = [u for u in urls if any(n in _path_lower(u) for n in needles)]

        results = [{"url": u} for u in matches[:limit]]

        return {
            "sitemap_url": sitemap_url,
            "bug_class": bug_class,
            "url_prefix": prefix or None,
            "total_in_sitemap": len(urls),
            "total_count": len(matches),
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # ctfsearch_search — Typesense-backed CTF writeup search
    # ------------------------------------------------------------------

    def ctfsearch_search(
        self,
        bug_class: str,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Query CTFsearch (HackMap) via its public Typesense search key.

        The key is a search-only key designed to be embedded client-side
        (it's already in their public JS bundle). Returns hits sorted by
        date desc.
        """
        bug_class = (bug_class or "").strip()
        if not bug_class:
            return {"error": "bug_class is required"}

        limit = min(max(1, int(limit)), 100)

        params = {
            "q": bug_class,
            "query_by": "title,content",
            "include_fields": "title,url,category,date,id",
            "sort_by": "date:desc",
            "per_page": str(limit),
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"https://{_CTFSEARCH_HOST}/collections/{_CTFSEARCH_COLLECTION}/documents/search",
                    params=params,
                    headers={
                        "X-TYPESENSE-API-KEY": _CTFSEARCH_KEY,
                        "User-Agent": "guide-agent/0.1",
                    },
                )
        except httpx.HTTPError as e:
            return {"error": f"CTFsearch request failed: {e}"}

        if resp.status_code != 200:
            return {
                "error": (
                    f"CTFsearch returned {resp.status_code}: "
                    f"{resp.text[:200]}"
                ),
            }

        body = resp.json()
        hits = body.get("hits") or []
        results = []
        for h in hits:
            doc = h.get("document") or {}
            results.append({
                "url": doc.get("url"),
                "title": doc.get("title"),
                "category": doc.get("category"),
                "date": doc.get("date"),
                "id": doc.get("id"),
            })

        return {
            "bug_class": bug_class,
            "total_count": body.get("found") or 0,
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # codereviewlab_search — 205 secure-code-review challenges via public API
    # ------------------------------------------------------------------

    def codereviewlab_search(
        self,
        bug_class: str,
        language: str | None = None,
        difficulty: str | None = None,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Query Code Review Lab's public catalog API.

        The /api/challenges endpoint returns all 205 challenges in one
        ~200KB response, fully tagged by vulnType + language + difficulty.
        Cached in-process so multiple calls in one agent run share one fetch.
        """
        bug_class = (bug_class or "").strip().lower()
        if not bug_class:
            return {"error": "bug_class is required"}

        needles = [s.strip() for s in bug_class.split("|") if s.strip()]
        if not needles:
            return {"error": "bug_class produced no search terms"}

        limit = min(max(1, int(limit)), 100)
        lang_norm = (language or "").strip().lower()
        diff_norm = (difficulty or "").strip().upper()

        try:
            challenges = _load_codereviewlab_challenges()
        except Exception as e:
            return {"error": f"Failed to load Code Review Lab catalog: {e}"}

        matches: list[dict[str, Any]] = []
        for c in challenges:
            vt = (c.get("vulnType") or "").lower()
            if not any(n in vt for n in needles):
                continue
            if lang_norm and lang_norm not in (c.get("language") or "").lower():
                continue
            if diff_norm and (c.get("difficulty") or "").upper() != diff_norm:
                continue
            cid = c.get("id")
            if not cid:
                continue
            matches.append({
                "url": f"https://www.codereviewlab.com/challenges/{cid}",
                "id": cid,
                "title": c.get("title") or "",
                "vuln_type": c.get("vulnType"),
                "language": c.get("language"),
                "difficulty": c.get("difficulty"),
                "points": c.get("points"),
                "platform": c.get("platform"),
                "description": (c.get("description") or "")[:300],
            })

        return {
            "bug_class": bug_class,
            "language": language,
            "difficulty": difficulty,
            "total_count": len(matches),
            "returned_count": min(len(matches), limit),
            "results": matches[:limit],
        }

    # ------------------------------------------------------------------
    # ctftime_events — CTFtime public API for upcoming/ongoing events
    # ------------------------------------------------------------------

    def ctftime_events(
        self,
        days_ahead: int = 60,
        min_weight: float = 0.0,
        limit: int = 15,
    ) -> dict[str, Any]:
        """List upcoming CTFs from CTFtime within a date window."""
        import time as _time
        from datetime import UTC, datetime, timedelta

        days_ahead = max(1, min(int(days_ahead), 365))
        limit = min(max(1, int(limit)), 100)

        try:
            min_weight = float(min_weight)
        except (TypeError, ValueError):
            return {"error": f"min_weight must be a number, got {min_weight!r}"}

        now = datetime.now(UTC)
        end = now + timedelta(days=days_ahead)
        params = {
            "limit": 100,
            "start": int(now.timestamp()),
            "finish": int(end.timestamp()),
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    "https://ctftime.org/api/v1/events/",
                    params=params,
                    headers={"User-Agent": "guide-agent/0.1"},
                )
        except httpx.HTTPError as e:
            return {"error": f"CTFtime request failed: {e}"}

        if resp.status_code != 200:
            return {
                "error": (
                    f"CTFtime returned {resp.status_code}: {resp.text[:200]}"
                ),
            }

        events = resp.json()
        if not isinstance(events, list):
            return {"error": "Unexpected CTFtime response shape"}

        filtered: list[dict[str, Any]] = []
        for e in events:
            weight = float(e.get("weight") or 0.0)
            if weight < min_weight:
                continue
            filtered.append({
                "url": e.get("ctftime_url"),
                "title": e.get("title"),
                "format": e.get("format"),
                "start": e.get("start"),
                "finish": e.get("finish"),
                "restrictions": e.get("restrictions"),
                "weight": weight,
                "onsite": e.get("onsite"),
                "duration": e.get("duration"),
                "external_url": e.get("url"),
                "participants": e.get("participants"),
            })

        # Sort by weight DESC then by start ASC
        filtered.sort(
            key=lambda x: (-x.get("weight", 0), x.get("start") or ""),
        )

        return {
            "days_ahead": days_ahead,
            "min_weight": min_weight,
            "fetched_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "total_count": len(filtered),
            "returned_count": min(len(filtered), limit),
            "results": filtered[:limit],
        }

    # ------------------------------------------------------------------
    # github_repos_by_stars — GitHub Search API sorted by stars
    # ------------------------------------------------------------------

    def github_repos_by_stars(
        self,
        query: str,
        min_stars: int = 0,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Search GitHub repos sorted by stars desc."""
        q = (query or "").strip()
        if not q:
            return {"error": "query is required"}

        try:
            min_stars = max(0, int(min_stars))
        except (TypeError, ValueError):
            return {"error": f"min_stars must be int, got {min_stars!r}"}

        limit = min(max(1, int(limit)), 100)

        if min_stars > 0 and "stars:" not in q:
            q = f"{q} stars:>{min_stars}"

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "guide-agent/0.1",
        }
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            with httpx.Client(timeout=15, headers=headers) as client:
                resp = client.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": q,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": limit,
                    },
                )
        except httpx.HTTPError as e:
            return {"error": f"GitHub Search failed: {e}"}

        if resp.status_code == 403:
            return {
                "error": (
                    "GitHub Search rate-limit or forbidden — set GITHUB_TOKEN "
                    "(30 req/min vs 10 unauthenticated)."
                ),
            }
        if resp.status_code != 200:
            return {
                "error": (
                    f"GitHub Search returned {resp.status_code}: "
                    f"{resp.text[:200]}"
                ),
            }

        data = resp.json()
        items = data.get("items", []) or []
        results: list[dict[str, Any]] = []
        for r in items[:limit]:
            results.append({
                "url": r.get("html_url"),
                "full_name": r.get("full_name"),
                "description": r.get("description") or "",
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
                "language": r.get("language"),
                "topics": r.get("topics") or [],
                "pushed_at": r.get("pushed_at"),
                "license": (r.get("license") or {}).get("spdx_id"),
                "archived": r.get("archived"),
            })

        return {
            "query": q,
            "total_count": data.get("total_count", 0),
            "returned_count": len(results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # prefetched_resource_search — instant DB-backed lookup
    # ------------------------------------------------------------------

    def prefetched_resource_search(
        self,
        bug_class: str,
        bug_class_id: int | None = None,
        source: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Look up prefetched resources tagged for this bug class.

        Thin wrapper around StateStore.query_prefetched. The first call
        for a given bug class triggers a one-time substring scan; later
        calls are pure JOIN lookups.
        """
        return self.state.query_prefetched(
            bug_class=bug_class,
            bug_class_id=bug_class_id,
            source=source,
            limit=limit,
        )

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


# ---------------------------------------------------------------------------
# codereviewlab_search helpers
# ---------------------------------------------------------------------------


_CODEREVIEWLAB_API_URL = "https://www.codereviewlab.com/api/challenges"
_codereviewlab_cache: list[dict[str, Any]] | None = None


def _load_codereviewlab_challenges() -> list[dict[str, Any]]:
    """Fetch + cache the full 205-challenge catalog. One download per process."""
    global _codereviewlab_cache
    if _codereviewlab_cache is not None:
        return _codereviewlab_cache

    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = client.get(
            _CODEREVIEWLAB_API_URL,
            headers={"User-Agent": "guide-agent/0.1"},
        )
    resp.raise_for_status()
    body = resp.json()
    challenges = body.get("challenges") if isinstance(body, dict) else None
    if not isinstance(challenges, list):
        raise ValueError("Unexpected API shape — no 'challenges' list")

    _codereviewlab_cache = challenges
    return challenges


# ---------------------------------------------------------------------------
# ctfsearch_search constants
# ---------------------------------------------------------------------------


# Public search-only Typesense key — extracted from CTFsearch's frontend JS
# bundle (index.43e1c602.js). Search-only keys are designed to be embedded
# client-side and are sent to every browser; they cannot mutate data.
_CTFSEARCH_HOST = "searchapi.hackmap.win"
_CTFSEARCH_COLLECTION = "writeups"
_CTFSEARCH_KEY = "Bl3uYook5z7LweUbGqy7dEDS4zNyoHEY"


# ---------------------------------------------------------------------------
# sitemap_search helpers
# ---------------------------------------------------------------------------


_sitemap_cache: dict[str, list[str]] = {}
_MAX_SITEMAP_DEPTH = 3
_MAX_SITEMAPS_VISITED = 25


def _load_sitemap_urls(sitemap_url: str) -> list[str]:
    """Fetch sitemap and walk indexes, returning a deduped URL list."""
    if sitemap_url in _sitemap_cache:
        return _sitemap_cache[sitemap_url]

    seen_sitemaps: set[str] = set()
    all_urls: list[str] = []
    seen_urls: set[str] = set()
    _walk_sitemap(sitemap_url, all_urls, seen_urls, seen_sitemaps, depth=0)
    _sitemap_cache[sitemap_url] = all_urls
    return all_urls


def _walk_sitemap(
    sm_url: str,
    all_urls: list[str],
    seen_urls: set[str],
    seen_sitemaps: set[str],
    depth: int,
) -> None:
    if depth > _MAX_SITEMAP_DEPTH:
        return
    if sm_url in seen_sitemaps:
        return
    if len(seen_sitemaps) >= _MAX_SITEMAPS_VISITED:
        return
    seen_sitemaps.add(sm_url)

    try:
        text = _fetch_feed_xml(sm_url)
    except httpx.HTTPError:
        return

    sub_sms, urls = _parse_sitemap_xml(text)
    for u in urls:
        if u and u not in seen_urls:
            seen_urls.add(u)
            all_urls.append(u)
    for sub in sub_sms:
        _walk_sitemap(sub, all_urls, seen_urls, seen_sitemaps, depth + 1)


def _parse_sitemap_xml(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (sub_sitemap_urls, url_locs) from a sitemap or index XML."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Sitemap XML parse error: {e}") from e

    sub_sms: list[str] = []
    urls: list[str] = []

    for elem in root.iter():
        local = elem.tag.split("}", 1)[-1]
        if local == "sitemap":
            loc = _xml_text(elem, "loc") or _xml_local_text(elem, "loc")
            if loc:
                sub_sms.append(loc)
        elif local == "url":
            loc = _xml_text(elem, "loc") or _xml_local_text(elem, "loc")
            if loc:
                urls.append(loc)

    return sub_sms, urls


def _xml_local_text(elem: Any, local_name: str) -> str:
    """Find first child matching local name (namespace-agnostic)."""
    for child in elem:
        if child.tag.split("}", 1)[-1] == local_name:
            return (child.text or "").strip() if child.text else ""
    return ""


# ---------------------------------------------------------------------------
# blog_feed_search helpers
# ---------------------------------------------------------------------------


_feed_cache: dict[str, list[dict[str, Any]]] = {}


def _load_blog_feed_entries(feed_url: str) -> list[dict[str, Any]]:
    """Fetch and parse an RSS or Atom feed into a list of entry dicts.

    Returned entries are sorted newest-first (feeds usually already are).
    Each entry: {title, link, summary, published}. For Blogger/Blogspot
    feeds (which paginate at ~25 entries per page) we walk pages until
    we exhaust the feed or hit a safety cap.
    """
    if feed_url in _feed_cache:
        return _feed_cache[feed_url]

    is_blogger = "blogspot.com/feeds/" in feed_url or "blogger.com/feeds/" in feed_url

    if not is_blogger:
        entries = _parse_feed_xml(_fetch_feed_xml(feed_url))
    else:
        entries = _fetch_blogger_paginated(feed_url, max_pages=10)

    _feed_cache[feed_url] = entries
    return entries


def _fetch_feed_xml(feed_url: str) -> str:
    """Single GET on a feed URL, returns the response body text."""
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = client.get(
            feed_url,
            headers={
                "User-Agent": "guide-agent/0.1",
                "Accept": "application/atom+xml, application/rss+xml, application/xml, */*",
            },
        )
    resp.raise_for_status()
    return resp.text


def _fetch_blogger_paginated(
    feed_url: str, max_pages: int = 20, page_size: int = 25,
) -> list[dict[str, Any]]:
    """Walk a Blogger feed using openSearch start-index/max-results.

    Blogger caps each page at 25 entries but often returns fewer due to
    payload-size limits. We keep paginating until a page returns zero new
    entries, or until openSearch totalResults says we've drained the feed.
    """
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(feed_url)
    base_path = urlunparse(parsed._replace(query=""))

    all_entries: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    total_results: int | None = None

    for page in range(max_pages):
        start_index = 1 + page * page_size
        page_url = (
            f"{base_path}?"
            f"{urlencode({'max-results': page_size, 'start-index': start_index})}"
        )
        try:
            text = _fetch_feed_xml(page_url)
        except httpx.HTTPError:
            break

        if total_results is None:
            m = re.search(r"totalResults[^>]*>(\d+)", text)
            if m:
                total_results = int(m.group(1))

        page_entries = _parse_feed_xml(text)
        if not page_entries:
            break
        new_count = 0
        for e in page_entries:
            link = e.get("link") or ""
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            all_entries.append(e)
            new_count += 1
        if new_count == 0:
            break
        if total_results is not None and len(all_entries) >= total_results:
            break
    return all_entries


def _parse_feed_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom into a uniform entry list. Stdlib only."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Feed XML parse error: {e}") from e

    tag = root.tag.lower()
    entries: list[dict[str, Any]] = []

    if "rss" in tag:
        # RSS 2.0: <rss><channel><item>...</item></channel></rss>
        for item in root.iter("item"):
            entries.append({
                "title": _xml_text(item, "title"),
                "link": _xml_text(item, "link"),
                "summary": _clean_summary(_xml_text(item, "description")),
                "published": _xml_text(item, "pubDate"),
            })
    else:
        # Atom: namespaced. Strip namespaces with iter() + endswith match.
        for entry in root.iter():
            if not entry.tag.endswith("}entry") and entry.tag != "entry":
                continue
            title = summary = published = ""
            # Track links by rel — prefer 'alternate' (the canonical post URL)
            # over 'self' / 'replies' / 'edit' which feeds also expose.
            alternate_link = ""
            fallback_link = ""
            for child in entry:
                local = child.tag.split("}", 1)[-1]
                if local == "title":
                    title = (child.text or "").strip()
                elif local == "link":
                    href = (child.get("href") or "").strip()
                    rel = (child.get("rel") or "alternate").lower()
                    if not href:
                        continue
                    if rel == "alternate" and not alternate_link:
                        alternate_link = href
                    elif not fallback_link:
                        fallback_link = href
                elif local == "summary" or (local == "content" and not summary):
                    summary = (child.text or "").strip()
                elif local in ("published", "updated") and not published:
                    published = (child.text or "").strip()
            entries.append({
                "title": title,
                "link": alternate_link or fallback_link,
                "summary": _clean_summary(summary),
                "published": published,
            })

    return entries


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_summary(raw: str, max_len: int = 500) -> str:
    """Strip HTML tags + collapse whitespace + cap length.

    Many feeds (Blogger especially) embed the full post HTML as the
    summary or content. Without stripping, the cache balloons and
    bug-class substring matches false-positive on body text.
    """
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_len]


def _xml_text(elem: Any, child_name: str) -> str:
    """Get .text of the first child with this tag (RSS — no namespaces)."""
    found = elem.find(child_name)
    return (found.text or "").strip() if found is not None and found.text else ""


# ---------------------------------------------------------------------------
# pentesterland_search helpers
# ---------------------------------------------------------------------------


_PENTESTERLAND_WRITEUPS_URL = "https://pentester.land/writeups.json"
_pentesterland_cache: list[dict[str, Any]] | None = None


def _load_pentesterland_writeups() -> list[dict[str, Any]]:
    """Fetch and cache the 3.6 MB writeups.json. One download per process."""
    global _pentesterland_cache
    if _pentesterland_cache is not None:
        return _pentesterland_cache

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(
            _PENTESTERLAND_WRITEUPS_URL,
            headers={"User-Agent": "guide-agent/0.1"},
        )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ValueError("Unexpected writeups.json shape — no 'data' list")

    _pentesterland_cache = data
    return data


_BOUNTY_NUMERIC_RE = re.compile(r"[\d,]+")


def _parse_bounty_amount(raw: Any) -> int:
    """Parse Pentester Land bounty string to int. '1,500' -> 1500, '-' -> 0."""
    if raw is None:
        return 0
    s = str(raw).strip()
    if not s or s == "-":
        return 0
    match = _BOUNTY_NUMERIC_RE.search(s)
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# hackerone_hacktivity_search helpers
# ---------------------------------------------------------------------------


_SEVERITY_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _build_hacktivity_lucene(
    bug_class: str,
    min_severity: str,
    min_bounty: int,
) -> str:
    """Build the Lucene query_string passed to HackerOne's search index.

    Severity is OR'd across all tiers >= the floor; bounty becomes an
    inclusive range. Bug class text is wrapped in parens to keep its
    Lucene precedence isolated from the AND'd filters.
    """
    bug_term = bug_class.strip()
    parts = [f"({bug_term})"]

    floor = _SEVERITY_RANK.get(min_severity, 3)
    sev_terms = [
        f"severity_rating:{name}"
        for name, rank in _SEVERITY_RANK.items()
        if rank >= floor
    ]
    if sev_terms:
        parts.append("(" + " OR ".join(sev_terms) + ")")

    if min_bounty > 0:
        parts.append(f"total_awarded_amount:[{min_bounty} TO *]")

    return " AND ".join(parts)



_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:[/.]|$)",
    re.IGNORECASE,
)


def _parse_github_repo(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a github.com URL. Returns ('','') on miss.

    Accepts:
      https://github.com/owner/repo
      https://github.com/owner/repo/
      https://github.com/owner/repo.git
      https://github.com/owner/repo/tree/branch
      https://github.com/owner/repo/tree/branch/subdir/...
    """
    if not url:
        return "", ""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return "", ""
    owner = match.group(1)
    repo = match.group(2).removesuffix(".git")
    return owner, repo


def _normalise_for_match(text: str) -> str:
    """Lowercase + strip non-alphanumeric. 'XSS Injection' → 'xssinjection'."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _score_repo_path(
    path: str,
    normalised_path: str,
    normalised_query: str,
) -> int:
    """Score how relevant a repo path is to the bug class query.

    Higher = better. Returns 0 to drop entirely.
    Heuristics:
      - Top-level directory match (XSS Injection/README.md) → big boost
      - README.md, NOTES.md, GUIDE.md filename → boost
      - Each path depth level → small penalty
      - Image/binary extensions → drop
    """
    if not normalised_query or normalised_query not in normalised_path:
        return 0

    # Drop obvious non-text artifacts
    lower = path.lower()
    if lower.endswith((
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf",
        ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".whl",
        ".exe", ".dll", ".so", ".dylib", ".bin",
        ".mp4", ".mp3", ".webm", ".mov", ".webp",
    )):
        return 0

    score = 10

    parts = path.split("/")
    # Top-level dir contains the match
    top_dir = parts[0] if parts else ""
    if normalised_query in _normalise_for_match(top_dir):
        score += 20

    # README / similar special files get a boost
    filename = parts[-1].lower() if parts else ""
    if filename in ("readme.md", "readme", "readme.rst", "readme.txt"):
        score += 15
    elif filename in ("notes.md", "guide.md", "overview.md", "index.md"):
        score += 8
    elif filename.endswith(".md"):
        score += 4

    # Depth penalty — top-level README beats a deeply nested one
    score -= max(0, (len(parts) - 1) * 2)

    return max(score, 1)
