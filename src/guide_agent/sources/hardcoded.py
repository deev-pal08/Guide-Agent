"""Hardcoded source pool helper.

Phase agents read the configured hardcoded source list (per phase) from
config.yaml and use it as web_search context — the model is instructed
to filter results so they belong to one of the configured sources.

If `deep_urls` for the active (phase, bug_class) are configured, the
renderer also lists those explicit URLs so the agent visits them directly
(via verify_url) IN ADDITION to running base-URL-scoped search. Results
are deduplicated by URL.

This module is a thin helper that surfaces the configured pool as a
ready-to-render context block for the system prompt. It does NOT fetch
or scrape source content itself — that's the model's job via web_search
and verify_url.
"""

from __future__ import annotations

from guide_agent.config import SourcesConfig


def render_hardcoded_pool(
    sources: SourcesConfig,
    phase: str,
    bug_class: str = "",
) -> str:
    """Render the hardcoded source pool for a phase as a context block.

    Returns an empty string for phases without a hardcoded pool
    (execute, research) — those are discovery-only.

    If `bug_class` is provided AND the SourcesConfig has predeclared
    deep_urls for (phase, bug_class), those URLs are added to the rendered
    block so the agent visits them directly. The agent is instructed to
    DEDUPLICATE deep_urls against web_search results before assigning.
    """
    pool = getattr(sources, phase, None)
    deep = sources.get_deep_urls(phase, bug_class) if bug_class else []

    if not pool and not deep:
        return ""

    lines: list[str] = []

    if pool:
        lines.append(f"## Hardcoded sources for the {phase} phase")
        lines.append(
            "Filter your web_search results so that, where possible, the resources "
            "you assign come from these authoritative sources. If a hardcoded "
            "source has nothing on the active bug class, fall back to intelligent "
            "research from the newsletter DB and the broader web."
        )
        for src in pool:
            extras: list[str] = []
            if src.feed_url:
                extras.append(f"feed_url for blog_feed_search: {src.feed_url}")
            if src.sitemap_url:
                extras.append(
                    f"sitemap_url for sitemap_search: {src.sitemap_url}",
                )
            if extras:
                lines.append(
                    f"- {src.name} — {src.base_url} ({'; '.join(extras)})",
                )
            else:
                lines.append(f"- {src.name} — {src.base_url}")

    if deep:
        if lines:
            lines.append("")
        lines.append(
            f"## Predeclared deep URLs for {phase} / {bug_class}"
        )
        lines.append(
            "These URLs are curated entry points for THIS specific bug class. "
            "Call verify_url on each, then INCLUDE them in your candidate list "
            "alongside your search results. DEDUPLICATE by URL (an entry that "
            "appears in both the deep list and the search results counts once)."
        )
        for url in deep:
            lines.append(f"- {url}")

    return "\n".join(lines)


def hardcoded_domains(sources: SourcesConfig, phase: str) -> list[str]:
    """Return the list of domains in the hardcoded pool for a phase.

    Useful for the model to construct domain-scoped queries
    (e.g., 'site:portswigger.net postmessage').
    """
    pool = getattr(sources, phase, None)
    if not pool:
        return []
    return [src.base_url for src in pool]
