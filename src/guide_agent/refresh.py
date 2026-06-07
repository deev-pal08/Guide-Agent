"""Per-bug-class fan-out fetcher — populate the prefetch DB on demand.

Design (per user spec):
  When you run `guide <bug-class> --<phase>` the first time for a new
  class, we fan out across every source (hardcoded + intelligent web
  search), filter for that bug class at the source, dedupe by URL,
  and store the results tagged with the bug class.

  Subsequent runs query the DB. When all rows for that class are in the
  user's consumed_resources ledger (everything read), the next run
  re-fans-out to top up. The --fresh flag forces a re-fan-out unconditionally.

Each adapter takes (bug_class, config?) and returns list[dict] of
{url, title, summary, metadata}. Adapters call the same live tools the
agent would otherwise use directly.
"""

from __future__ import annotations

import logging
from typing import Any

from guide_agent.agent.tools import Tools
from guide_agent.config import AppConfig
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-class source adapters
# ---------------------------------------------------------------------------


def fetch_hacktivity_for_class(
    tools: Tools, bug_class: str, limit: int = 100,
) -> list[dict[str, Any]]:
    """Pull H1 disclosed reports for this bug class — all severities.

    Hacktivity's Lucene query builder only accepts a single literal term,
    NOT a '|'-OR expansion — multi-term breaks the H1 GraphQL parser. So
    pass only the canonical bug class name here.
    """
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    # Pull high+critical (typically the most interesting), then medium+low.
    for min_sev in ("medium", "none"):
        r = tools.hackerone_hacktivity_search(
            bug_class=bug_class,
            min_severity=min_sev,
            min_bounty=0,
            limit=limit,
        )
        if "error" in r:
            logger.warning("hacktivity fetch failed (%s): %s", min_sev, r["error"])
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("title") or "",
                "summary": (
                    f"sev={x.get('severity')} bounty=${x.get('bounty', 0)} "
                    f"cwe={x.get('cwe') or '-'} team={x.get('team_handle') or '-'}"
                ),
                "metadata": {
                    "severity": x.get("severity"),
                    "bounty": x.get("bounty"),
                    "cwe": x.get("cwe"),
                    "team_handle": x.get("team_handle"),
                    "votes": x.get("votes"),
                    "report_id": x.get("report_id"),
                },
            })
    return out


def fetch_pentesterland_for_class(
    tools: Tools, terms: list[str], limit: int = 200,
) -> list[dict[str, Any]]:
    """Pentester Land matches bug_class as substring against the Bugs[] tag
    array on each writeup. The matcher takes a single term — to use the
    full expansion we iterate each synonym and dedupe by URL.
    """
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for term in terms:
        r = tools.pentesterland_search(
            bug_class=term, min_bounty=0, limit=limit,
        )
        if "error" in r:
            logger.warning("pentesterland fetch (%s) failed: %s", term, r["error"])
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("title") or "",
                "summary": (
                    f"bounty=${x.get('bounty', 0)} "
                    f"programs={','.join(x.get('programs') or [])[:80]}"
                ),
                "metadata": {
                    "bounty": x.get("bounty"),
                    "authors": x.get("authors"),
                    "programs": x.get("programs"),
                    "bugs": x.get("bugs"),
                    "publication_date": x.get("publication_date"),
                    "matched_term": term,
                },
            })
    return out


def fetch_ctfsearch_for_class(
    tools: Tools, terms: list[str], limit: int = 50,
) -> list[dict[str, Any]]:
    """CTFsearch is Typesense (full-text). Each query gets per-term hits;
    dedupe by URL across the term sweep."""
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for term in terms:
        r = tools.ctfsearch_search(bug_class=term, limit=limit)
        if "error" in r:
            logger.warning("ctfsearch (%s) failed: %s", term, r["error"])
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("title") or "",
                "summary": (
                    f"category={x.get('category') or '-'} date={x.get('date') or '-'}"
                ),
                "metadata": {
                    "category": x.get("category"),
                    "date": x.get("date"),
                    "matched_term": term,
                },
            })
    return out


def fetch_codereviewlab_for_class(
    tools: Tools, terms: list[str], limit: int = 50,
) -> list[dict[str, Any]]:
    """Code Review Lab matches bug_class against its vulnType taxonomy.
    Iterate each expanded term and dedupe by challenge URL."""
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for term in terms:
        r = tools.codereviewlab_search(bug_class=term, limit=limit)
        if "error" in r:
            logger.warning("codereviewlab (%s) failed: %s", term, r["error"])
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("title") or "",
                "summary": (
                    f"vulnType={x.get('vuln_type') or '-'} "
                    f"language={x.get('language') or '-'} "
                    f"difficulty={x.get('difficulty') or '-'} "
                    f"points={x.get('points') or 0}"
                ),
                "metadata": {
                    "vuln_type": x.get("vuln_type"),
                    "language": x.get("language"),
                    "difficulty": x.get("difficulty"),
                    "points": x.get("points"),
                    "platform": x.get("platform"),
                    "matched_term": term,
                },
            })
    return out


def fetch_blog_feed_for_class(
    tools: Tools, feed_url: str, expanded_query: str, limit: int = 50,
) -> list[dict[str, Any]]:
    """Blog feed tool natively supports '|'-OR — pass the expansion directly."""
    r = tools.blog_feed_search(
        feed_url=feed_url, bug_class=expanded_query, limit=limit,
    )
    if "error" in r:
        logger.warning("blog feed %s failed: %s", feed_url, r["error"])
        return []
    out: list[dict[str, Any]] = []
    for x in r.get("results", []):
        if not x.get("url"):
            continue
        out.append({
            "url": x["url"],
            "title": x.get("title") or "",
            "summary": x.get("summary") or "",
            "metadata": {
                "feed_url": feed_url,
                "published": x.get("published"),
            },
        })
    return out


def fetch_sitemap_for_class(
    tools: Tools,
    sitemap_url: str,
    expanded_query: str,
    url_prefix: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Sitemap tool natively supports '|'-OR — pass expansion directly."""
    r = tools.sitemap_search(
        sitemap_url=sitemap_url,
        bug_class=expanded_query,
        url_prefix=url_prefix,
        limit=limit,
    )
    if "error" in r:
        logger.warning("sitemap %s failed: %s", sitemap_url, r["error"])
        return []
    out: list[dict[str, Any]] = []
    for x in r.get("results", []):
        if not x.get("url"):
            continue
        out.append({
            "url": x["url"],
            "title": "",
            "summary": "",
            "metadata": {
                "sitemap_url": sitemap_url,
                "url_prefix": url_prefix,
            },
        })
    return out


def fetch_github_repo_for_class(
    tools: Tools, repo_url: str, bug_class: str, limit: int = 15,
) -> list[dict[str, Any]]:
    """github_repo_search matches against normalised file paths — '|'
    isn't a tokeniser here, so pass the canonical bug class only.

    We filter the result set to text/doc files (README / .md / .rst /
    .txt) — source-code files (.py, .ts, .php, etc.) in vulnerable
    apps rarely carry per-bug-class learning value and bloat the DB
    with noise (e.g. Laravel vendor files happen to contain 'injection'
    in their paths).
    """
    r = tools.github_repo_search(
        repo_url=repo_url, bug_class=bug_class, limit=limit * 3,
    )
    if "error" in r:
        logger.warning("github repo %s failed: %s", repo_url, r["error"])
        return []
    out: list[dict[str, Any]] = []
    for x in r.get("results", []):
        path = (x.get("path") or "").lower()
        if not path.endswith(_GITHUB_DOC_EXTENSIONS):
            continue
        url = x.get("blob_url") or x.get("raw_url")
        if not url:
            continue
        out.append({
            "url": url,
            "title": x.get("path") or "",
            "summary": f"repo path: {x.get('path')}",
            "metadata": {
                "repo_url": repo_url,
                "path": x.get("path"),
                "raw_url": x.get("raw_url"),
            },
        })
        if len(out) >= limit:
            break
    return out


# Text/doc file extensions worth surfacing from a github repo walk —
# everything else (source code, configs, binaries) gets dropped at the
# refresh layer to keep the prefetched DB high-signal.
_GITHUB_DOC_EXTENSIONS = (
    ".md", ".rst", ".txt", ".asciidoc", ".adoc",
    "readme", "/readme",
)


def fetch_newsletter_for_class(
    config: AppConfig, bug_class: str, limit: int = 200,
) -> list[dict[str, Any]]:
    """Read pre-tagged articles from the newsletter agent's DB.

    Newsletter-agent runs with `--topic <bug_class>` tag every surviving
    article in its `article_tags` table. We JOIN that with seen_articles
    and surface the result. Read-only — guide-agent never writes to
    newsletter's DB. Returns empty list if newsletter integration is
    disabled or the article_tags table doesn't exist yet.
    """
    if not config.newsletter.enabled or not config.newsletter.project_dir:
        return []
    from guide_agent.sources.newsletter import NewsletterReader

    try:
        reader = NewsletterReader(config.newsletter.project_dir)
    except FileNotFoundError as e:
        logger.warning("Newsletter DB not found: %s", e)
        return []
    if not reader.is_available():
        return []

    try:
        rows = reader.get_tagged_articles(bug_class, limit=limit)
    finally:
        reader.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("url"):
            continue
        out.append({
            "url": r["url"],
            "title": r.get("title") or "",
            "summary": (
                f"newsletter_source={r.get('source_id') or '-'} "
                f"first_seen={r.get('first_seen') or '-'}"
            ),
            "metadata": {
                "newsletter_source_id": r.get("source_id"),
                "newsletter_first_seen": r.get("first_seen"),
                "newsletter_tagged_at": r.get("tagged_at"),
                "tag_source": r.get("tag_source"),
            },
        })
    return out


def fetch_web_search_for_class(
    tools: Tools, queries: list[str],
) -> list[dict[str, Any]]:
    """Run intelligent web_search queries and collect results."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in queries:
        r = tools.web_search(query=q)
        if "error" in r:
            logger.warning("web_search %r failed: %s", q, r["error"])
            continue
        for x in r.get("results", []):
            url = (x.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "url": url,
                "title": x.get("title") or "",
                "summary": x.get("description") or "",
                "metadata": {
                    "search_query": q,
                    "search_source": x.get("source"),
                },
            })
    return out


def fetch_ctftime_for_execute(
    tools: Tools, days_ahead: int = 60, min_weight: float = 0.0, limit: int = 50,
) -> list[dict[str, Any]]:
    """Pull upcoming CTFs from CTFtime — ambient, NOT bug-class filtered."""
    r = tools.ctftime_events(
        days_ahead=days_ahead, min_weight=min_weight, limit=limit,
    )
    if "error" in r:
        logger.warning("ctftime fetch failed: %s", r["error"])
        return []
    out: list[dict[str, Any]] = []
    for e in r.get("results", []):
        url = e.get("url")
        if not url:
            continue
        out.append({
            "url": url,
            "title": e.get("title") or "",
            "summary": (
                f"format={e.get('format')} restrictions={e.get('restrictions')} "
                f"start={e.get('start')} weight={e.get('weight')}"
            ),
            "metadata": {
                "format": e.get("format"),
                "start": e.get("start"),
                "finish": e.get("finish"),
                "restrictions": e.get("restrictions"),
                "weight": e.get("weight"),
                "onsite": e.get("onsite"),
                "duration": e.get("duration"),
                "external_url": e.get("external_url"),
                "participants": e.get("participants"),
            },
        })
    return out


def fetch_popular_oss_for_execute(
    tools: Tools, queries: list[str], min_stars: int = 5000, limit: int = 25,
) -> list[dict[str, Any]]:
    """Pull popular OSS projects from GitHub Search — ambient, NOT bug-class
    filtered. Each query targets a different language/ecosystem to spread the
    pool across the OSS landscape."""
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        r = tools.github_repos_by_stars(
            query=q, min_stars=min_stars, limit=limit,
        )
        if "error" in r:
            logger.warning("github_repos_by_stars (%s) failed: %s", q, r["error"])
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("full_name") or "",
                "summary": (
                    f"stars={x.get('stars')} language={x.get('language') or '-'} "
                    f"topics={','.join((x.get('topics') or [])[:5])} "
                    f"{(x.get('description') or '')[:200]}"
                ),
                "metadata": {
                    "stars": x.get("stars"),
                    "forks": x.get("forks"),
                    "language": x.get("language"),
                    "topics": x.get("topics"),
                    "pushed_at": x.get("pushed_at"),
                    "license": x.get("license"),
                    "archived": x.get("archived"),
                    "query": q,
                },
            })
    return out


def fetch_hunting_tools_for_class(
    tools: Tools, bug_class: str, terms: list[str], min_stars: int = 50, limit: int = 20,
) -> list[dict[str, Any]]:
    """Pull GitHub repos that are HUNTING TOOLS for the current bug class.

    Used to populate the Tools Section of the execute plan. Searches like
    'xss exploitation', 'jwt cracker', 'postmessage fuzzer' — repos that
    are tools to RUN, not codebases to audit. Popularity floor is much
    lower than Task 2 OSS targets (50 stars vs 5000+) because security
    tooling is niche; a 200-star Burp extension is genuinely useful.
    """
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # Build tool-hunting queries per synonym. Keep canonical + top synonyms.
    needles = [bug_class] + [t for t in terms if t != bug_class][:3]
    suffixes = [
        "scanner",
        "exploitation",
        "fuzzer",
        "burp extension",
        "tool",
    ]
    queries = []
    for n in needles:
        for s in suffixes:
            queries.append(f"{n} {s}")

    for q in queries:
        r = tools.github_repos_by_stars(
            query=q, min_stars=min_stars, limit=limit,
        )
        if "error" in r:
            logger.warning(
                "github_repos_by_stars hunting (%s) failed: %s", q, r["error"],
            )
            continue
        for x in r.get("results", []):
            url = x.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append({
                "url": url,
                "title": x.get("full_name") or "",
                "summary": (
                    f"stars={x.get('stars')} "
                    f"{(x.get('description') or '')[:200]}"
                ),
                "metadata": {
                    "stars": x.get("stars"),
                    "language": x.get("language"),
                    "topics": x.get("topics"),
                    "pushed_at": x.get("pushed_at"),
                    "license": x.get("license"),
                    "archived": x.get("archived"),
                    "matched_query": q,
                    "is_tool": True,
                },
            })
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def populate_for_bug_class(
    config: AppConfig,
    state: StateStore,
    tools: Tools,
    bug_class: str,
    phase: str,
    expanded_query: str | None = None,
) -> dict[str, dict[str, int]]:
    """Fan out across all sources for a bug class, dedupe + tag + store.

    Resources are stored tagged with the CANONICAL `bug_class` (not the
    individual synonym they matched). `expanded_query` (if provided) is
    the '|'-joined synonym string — adapters that natively understand
    '|'-OR receive it directly; adapters whose underlying tools take a
    single literal term iterate over each synonym and dedup. The
    canonical name is always tried for those single-term sources.

    The set of universal tools fired depends on the phase intent:
      learn    → discovery-heavy (web search, github repos for cheatsheets)
      examples → writeups + reports (hacktivity, pentesterland, ctfsearch)
      practice → labs + challenges (CTF index + targeted web search)
      execute  → live programs (web search for active bounty/CTF scope)
    Per-source feeds + sitemaps from config are always used for the
    matching phase pool.

    Returns per-source counts so the CLI can show what was fetched.
    """
    bug_class = bug_class.strip().lower()
    if not bug_class:
        return {}
    query = expanded_query.strip() if expanded_query else bug_class
    if not query:
        query = bug_class

    # Split expansion into individual terms for adapters whose underlying
    # tools take a single literal (hacktivity, pentesterland, ctfsearch,
    # github_repo_search). Order: canonical first, then synonyms.
    terms: list[str] = []
    for t in query.split("|"):
        tn = t.strip().lower()
        if tn and tn not in terms:
            terms.append(tn)
    if bug_class not in terms:
        terms.insert(0, bug_class)

    report: dict[str, dict[str, int]] = {}

    def _persist(source_id: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            report[source_id] = {"fetched": 0, "inserted": 0, "tagged": 0}
            return
        result = state.add_resources_for_bug_class(source_id, bug_class, rows)
        result["fetched"] = len(rows)
        report[source_id] = result
        logger.info(
            "%s [%s/%s]: fetched=%d inserted=%d tagged=%d",
            source_id, bug_class, phase, len(rows),
            result["inserted"], result["tagged"],
        )

    flags = _PHASE_SOURCE_FLAGS.get(phase, _PHASE_SOURCE_FLAGS["examples"])

    # ------------------------------------------------------------------
    # Universal data tools (phase-gated)
    # ------------------------------------------------------------------
    if flags.get("hacktivity"):
        # hacktivity: canonical-only (Lucene parser breaks on '|').
        _persist("hacktivity", fetch_hacktivity_for_class(tools, bug_class))
    if flags.get("pentesterland"):
        _persist("pentesterland", fetch_pentesterland_for_class(tools, terms))
    if flags.get("ctfsearch"):
        _persist("ctfsearch", fetch_ctfsearch_for_class(tools, terms))
    if flags.get("codereviewlab"):
        _persist("codereviewlab", fetch_codereviewlab_for_class(tools, terms))
    if flags.get("newsletter"):
        _persist(
            "newsletter",
            fetch_newsletter_for_class(config, bug_class),
        )

    # ------------------------------------------------------------------
    # Per-source feeds + sitemaps from this phase's hardcoded pool
    # ------------------------------------------------------------------
    phase_sources = getattr(config.sources, phase, [])
    seen_endpoints: set[str] = set()
    for src in phase_sources:
        if src.feed_url and src.feed_url not in seen_endpoints:
            seen_endpoints.add(src.feed_url)
            _persist(
                f"feed:{src.name}",
                fetch_blog_feed_for_class(tools, src.feed_url, query),
            )
        if src.sitemap_url and src.sitemap_url not in seen_endpoints:
            seen_endpoints.add(src.sitemap_url)
            prefix = src.base_url if src.base_url.endswith("/") else src.base_url + "/"
            _persist(
                f"sitemap:{src.name}",
                fetch_sitemap_for_class(
                    tools, src.sitemap_url, query, prefix,
                ),
            )
        if flags.get("github_repos") and _is_github_repo_url(src.base_url or ""):
            _persist(
                f"github:{src.name}",
                fetch_github_repo_for_class(tools, src.base_url, bug_class),
            )

    # ------------------------------------------------------------------
    # Execute-phase always-include hardcoded URLs.
    # The HTB/picoCTF/TryHackMe CTF calendars are gated SPAs — no feed,
    # no sitemap, no API. We surface them as bare destinations so they
    # ALWAYS appear in Task 3 alongside the CTFtime-pulled events.
    # ------------------------------------------------------------------
    if phase == "execute":
        always_include_rows = [
            {
                "url": src.base_url,
                "title": src.name,
                "summary": f"Hardcoded {phase} destination — {src.name}",
                "metadata": {"hardcoded": True, "name": src.name},
            }
            for src in phase_sources
            if src.base_url
        ]
        _persist("hardcoded_hubs", always_include_rows)

    # ------------------------------------------------------------------
    # Intelligent web search (phase-tuned query templates)
    # ------------------------------------------------------------------
    if flags.get("web_search"):
        templates = _PHASE_WEB_QUERIES.get(phase, _PHASE_WEB_QUERIES["examples"])
        web_queries = [tpl.format(bc=bug_class) for tpl in templates]
        # Add one writeup/lab/scope synonym query per top-3 synonym for
        # phases that benefit (examples + practice). learn + execute use
        # tighter queries already.
        if phase in ("examples", "practice"):
            syn_for_web = [t for t in terms if t != bug_class][:3]
            suffix = "writeup" if phase == "examples" else "lab"
            for syn in syn_for_web:
                web_queries.append(f"{syn} {suffix}")
        _persist("web_search", fetch_web_search_for_class(tools, web_queries))

    # ------------------------------------------------------------------
    # Execute-only AMBIENT discovery (not bug-class filtered)
    #
    # Execute opportunities — popular OSS to audit, upcoming CTFs — are
    # ambient: they're valuable regardless of which bug class the user is
    # currently drilling. We fetch them once and tag with the active class
    # so the prefetch DB stays per-class, but the underlying selection is
    # popularity / recency based.
    # ------------------------------------------------------------------
    if phase == "execute":
        # Popular OSS — spread queries across major ecosystems to give the
        # user a diverse target pool. Each query has its own popularity
        # floor and language scope. 5000+ stars is the minimum bar.
        oss_queries = [
            "language:javascript",
            "language:typescript",
            "language:python",
            "language:go",
            "language:rust",
            "language:java",
            "topic:framework",
            "topic:api",
        ]
        _persist(
            "popular_oss",
            fetch_popular_oss_for_execute(
                tools, queries=oss_queries, min_stars=5000, limit=10,
            ),
        )

        # Upcoming CTFs — 60-day window, no quality floor (let the user
        # pick). Returns sorted by CTFtime weight DESC.
        _persist(
            "ctftime",
            fetch_ctftime_for_execute(
                tools, days_ahead=60, min_weight=0.0, limit=30,
            ),
        )

        # Hunting tools (the Tools Section) — bug-class-specific GitHub
        # repos that are tools to RUN (scanners, fuzzers, Burp extensions).
        # Tagged with `source=hunting_tools` so the planner can pull them
        # separately to populate `tools_section` on the Plan.
        _persist(
            "hunting_tools",
            fetch_hunting_tools_for_class(
                tools, bug_class=bug_class, terms=terms,
                min_stars=50, limit=10,
            ),
        )

    return report


# Which universal data tools fire for each phase. Per-source feeds + sitemaps
# from config.sources.<phase> are always used regardless of flag map.
_PHASE_SOURCE_FLAGS: dict[str, dict[str, bool]] = {
    "learn": {
        # Theory phase — skip writeups, use cheatsheets / docs / web search.
        # Newsletter on: research papers + methodology posts surface here.
        "hacktivity": False,
        "pentesterland": False,
        "ctfsearch": False,
        "codereviewlab": False,
        "newsletter": True,
        "github_repos": True,
        "web_search": True,
    },
    "examples": {
        # Writeups + disclosed reports — everything on.
        # codereviewlab challenges have exploit + mitigation explanations
        # that double as solved examples, so include them here too.
        # Newsletter on: real attack techniques + research papers are the
        # bulk of newsletter content for examples phase.
        "hacktivity": True,
        "pentesterland": True,
        "ctfsearch": True,
        "codereviewlab": True,
        "newsletter": True,
        "github_repos": True,
        "web_search": True,
    },
    "practice": {
        # Labs + CTF challenges — CTFsearch (CTF walkthroughs are pseudo-labs)
        # plus codereviewlab (source-code-review training) plus github
        # vulnerable apps + targeted web search. No newsletter — articles
        # are read-content not do-content.
        "hacktivity": False,
        "pentesterland": False,
        "ctfsearch": True,
        "codereviewlab": True,
        "newsletter": False,
        "github_repos": True,
        "web_search": True,
    },
    "execute": {
        # Live programs + CTFs — bug-class filtering is mostly noise here.
        # OSS targets + CTFs are AMBIENT discoveries (any active program/CTF
        # is valuable); selection should be by popularity + recency, not by
        # which bug class the user happens to be drilling.
        # The execute orchestrator below fires dedicated adapters
        # (ctftime + popular_oss) that do NOT filter by bug class.
        "hacktivity": False,
        "pentesterland": False,
        "ctfsearch": False,
        "codereviewlab": False,
        "newsletter": False,
        "github_repos": False,
        "web_search": True,
    },
}


# Web-search query templates per phase, `{bc}` substituted with canonical name.
_PHASE_WEB_QUERIES: dict[str, list[str]] = {
    "learn": [
        "{bc} tutorial",
        "{bc} cheatsheet",
        "{bc} theory deep dive",
        "{bc} attack fundamentals",
    ],
    "examples": [
        "{bc} writeup bug bounty",
        "{bc} exploitation guide",
        "{bc} CVE disclosure",
        "{bc} advanced techniques",
    ],
    "practice": [
        "{bc} lab challenge",
        "{bc} CTF challenge",
        "vulnerable application {bc}",
        "{bc} hands-on exercise",
        # Platform-targeted: gated platforms (THM/HTB/picoCTF) won't be
        # crawlable but Brave returns deep room/challenge URLs by writeup
        # cross-references that mention them. Multiple variants per platform
        # to push past Brave's 10-results-per-query cap.
        "site:tryhackme.com/room {bc}",
        "site:tryhackme.com/room {bc} walkthrough",
        "site:tryhackme.com/path {bc}",
        "site:tryhackme.com {bc} challenge",
        "site:hackthebox.com {bc}",
        "site:academy.hackthebox.com/course/preview {bc}",
        "site:hackthebox.com {bc} writeup",
        "site:app.hackthebox.com {bc}",
        "site:play.picoctf.org/practice/challenge {bc}",
        "site:play.picoctf.org {bc} category",
        "picoCTF {bc} challenge writeup",
    ],
    "execute": [
        "bug bounty program {bc} in scope",
        "open source project {bc} vulnerable",
        "live CTF {bc} challenge",
        "{bc} hackathon",
        # Platform-specific CTF calendars that don't register on CTFtime —
        # bug class is mostly noise here, but Brave will surface the
        # event/competition pages tied to each platform's calendar.
        "picoCTF competition 2026 register",
        "HackTheBox CTF event upcoming",
        "TryHackMe advent of cyber",
        "Lakera Gandalf CTF",
        "Wiz CTF competition",
        "BSides CTF 2026 registration",
        "DEF CON CTF qualifier 2026",
        "AI red team competition 2026",
    ],
}


def _is_github_repo_url(url: str) -> bool:
    """True for github.com/<owner>/<repo>[/...] URLs only.

    Excludes github.com/advisories, github.com/orgs/X, github.com/topics/Y,
    etc. — those aren't repositories the Git Tree API can walk.
    """
    import re
    return bool(re.match(
        r"^https?://github\.com/[^/\s]+/[^/\s]+(?:/|$)",
        url.strip(),
        re.IGNORECASE,
    )) and not re.match(
        r"^https?://github\.com/"
        r"(?:advisories|orgs|topics|sponsors|marketplace|features|"
        r"trending|collections|enterprise|pricing|about)/",
        url.strip(),
        re.IGNORECASE,
    )


def populate_if_empty(
    config: AppConfig,
    state: StateStore,
    tools: Tools,
    bug_class: str,
    bug_class_id: int,
    phase: str,
    force: bool = False,
    expanded_query: str | None = None,
) -> tuple[bool, dict[str, dict[str, int]]]:
    """Auto-trigger: fan-out only if (force OR no unread rows).

    Returns (did_fetch, report). `expanded_query` is forwarded to
    populate_for_bug_class — use ensure_expansion() to build one.
    """
    if not force:
        unread = state.unread_count_for_bug_class(bug_class, bug_class_id)
        if unread > 0:
            logger.info(
                "DB has %d unread resources for %s — skipping fan-out",
                unread, bug_class,
            )
            return False, {}

    logger.info("Fanning out fetch for %s (phase=%s, force=%s)",
                bug_class, phase, force)
    report = populate_for_bug_class(
        config, state, tools, bug_class, phase,
        expanded_query=expanded_query,
    )
    return True, report
