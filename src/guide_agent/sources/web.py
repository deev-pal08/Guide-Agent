"""Web source orchestration helper.

The actual web search happens through the Tools.web_search method which
calls Brave/Tavily/Exa in parallel. This module exists for symmetry with
hardcoded.py and newsletter.py — it surfaces phase-specific web-search
guidance and provider availability for the prompt context.
"""

from __future__ import annotations

from guide_agent.config import SearchConfig


def render_web_search_availability(search: SearchConfig) -> str:
    """One-line summary of which web search providers are enabled."""
    if not search.enabled:
        return "## Web search: DISABLED in config"

    providers = []
    if search.brave.enabled:
        providers.append("Brave")
    if search.tavily.enabled:
        providers.append("Tavily")
    if search.exa.enabled:
        providers.append("Exa")

    if not providers:
        return "## Web search: enabled, but no providers configured"

    return (
        f"## Web search providers active: {', '.join(providers)}. "
        f"Calls fan out to all providers in parallel and dedupe by URL — "
        f"a single web_search call returns merged results."
    )
