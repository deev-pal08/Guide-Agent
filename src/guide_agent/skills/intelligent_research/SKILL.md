---
name: intelligent_research
description: Cross-cutting research workflow used inside every phase skill. Defines the prefetch-first model — query the local DB before reaching for the network — and the live-tool fallback set (hacktivity, pentesterland, ctfsearch, codereviewlab, blog_feed_search, sitemap_search, github_repo_search, github_repos_by_stars, ctftime_events, newsletter_query, web_search). Phase skills call into this, never called directly by the user.
---

# Intelligent Research

This is the shared discovery workflow that every phase skill uses. The phase skill decides WHAT to search for (informed by phase semantics); this skill describes HOW to combine the local prefetched DB + live tools efficiently.

## Prefetch-first model

Before every phase invocation, the CLI runs a per-bug-class fan-out (`populate_for_bug_class`) that pulls from every applicable source for THIS phase and writes results into the `prefetched_resources` table tagged with the bug class. By the time the planner brain runs, the DB already contains the URL pool for the active (bug_class, phase) pair.

**Rule for every phase skill: call `prefetched_resource_search` FIRST.** Only fall back to live tools if:
- `returned_count` is too low for the user's `target_hours`, OR
- The user context contains `FRESH_FETCH=true` (`--fresh` CLI flag).

## Source layer per phase

The fan-out gates which adapters fire per phase. Live fallback uses the same set:

| Phase | Adapters that fire | Live tools available |
|---|---|---|
| **learn** | `web_search`, `github_repo_search` (curated docs), `sitemap_search`, `blog_feed_search` | + `newsletter_query`, `verify_url` |
| **examples** | `hacktivity`, `pentesterland`, `ctfsearch`, `codereviewlab`, `sitemap_search`, `blog_feed_search`, `github_repo_search` (curated archives), `web_search` | + `newsletter_query`, `verify_url` |
| **practice** | `ctfsearch`, `codereviewlab`, `sitemap_search`, `blog_feed_search`, `github_repo_search` (vulnerable apps `.md` only), `web_search` (with platform queries for THM/HTB/picoCTF) | + `newsletter_query`, `verify_url` |
| **execute** | `popular_oss` (github_repos_by_stars), `ctftime`, `hunting_tools` (bug-class-specific github tools), `web_search`, `hardcoded_hubs` (HTB/picoCTF/THM bare URLs) | + `hackerone_hacktivity_search` (for Task 1 smart prioritization), `verify_url` |
| **research** | NONE — discovery-only, no prefetch | `web_search`, `verify_url`, `newsletter_query`, ArXiv / venue proceedings via web |

## Workflow inside a phase agent loop

1. **`prefetched_resource_search(bug_class, bug_class_id)`** — ALWAYS the first call. Returns DB-cached resources tagged for this class, automatically excluding URLs in the user's consumed_resources ledger.
2. **`search_consumed_resources`** — supplementary check if you have additional URLs in mind not from the DB.
3. **Live fallback (only if needed):**
   - Examples phase: `hackerone_hacktivity_search` + `pentesterland_search` + `ctfsearch_search` + `codereviewlab_search` + `blog_feed_search` + `sitemap_search` + `web_search` (all in ONE turn).
   - Practice phase: `ctfsearch_search` + `codereviewlab_search` + `sitemap_search` + platform-targeted `web_search`.
   - Execute phase: `github_repos_by_stars` (popular OSS or hunting tools) + `ctftime_events` + `web_search` + `hackerone_hacktivity_search` (smart-prioritize Task 1).
   - Learn phase: `newsletter_query` + `web_search` + `sitemap_search` + `blog_feed_search`.
4. **`verify_url`** in ONE turn on every candidate. Use returned `page_title` as `resource_name`. Drop 404s.
5. **(optional)** `read_skill_reference(<phase>, "REFERENCES.md")` for phase-specific methodology depth.
6. **Final turn** — emit Plan JSON.

## Bug-class term expansion (Lever 3)

Before fan-out, the CLI calls `ensure_expansion(bug_class)` which uses a one-time Haiku call (~$0.0003, cached forever) to expand the canonical bug class name into 6-10 search terms covering synonyms / related techniques / abbreviations. Example: `postmessage` → `[postmessage, window.postmessage, cross-window communication, cross-origin messaging, postmessage origin validation, targetorigin, postmessage xss, ...]`.

This expansion is automatically used by all adapters that benefit from it (pentesterland, ctfsearch, codereviewlab, blog_feed_search, sitemap_search, web_search). Single-term tools (hacktivity, github_repo_search) receive the canonical bug class only — their parsers don't accept multi-term queries.

## Deduplication rules

Cross-source dedup happens at TWO layers:
- **In each adapter** (per-tool): URL dedup across multiple synonym queries.
- **At DB write** (`StateStore.add_resources_for_bug_class`): UNIQUE constraint on URL ensures the same URL across sources only inserts once; tag table ensures one (resource, bug_class) tag.

The DB is the canonical dedup point. The planner reads from DB and gets a clean URL list.

## Ranking heuristics

When choosing which DB rows to surface, prioritize:

1. **Recency** for examples/practice/execute (use `fetched_at` or per-source date metadata).
2. **Authority signal** — for hacktivity rows, sort by `severity` then `bounty`; for popular_oss, by `stars`; for ctftime, by `weight`; for codereviewlab, by `difficulty` (HARD > MEDIUM > EASY for advanced users).
3. **Source diversity** — don't surface 10 results all from one source if you have 5 sources contributing.
4. **Topic depth** for learn (longer authoritative docs beat short skims).

## Query construction (live fallback only)

Per-source tools (`pentesterland_search`, `ctfsearch_search`, `codereviewlab_search`, `blog_feed_search`, `sitemap_search`) accept the `|`-joined expansion natively — pass the expanded string directly.

For `web_search` (Brave/Tavily/Exa parse free text, not Lucene OR), vary queries along:
- **Sub-area** — "postMessage origin validation", "postMessage iframe sandbox bypass"
- **Source-type** — "<bug class> hackerone disclosed report", "<bug class> CVE writeup", "<bug class> arxiv paper"
- **Stack** — "<bug class> React", "<bug class> Node.js", "<bug class> Spring Boot"
- **Temporal** — "<bug class> 2026", "<bug class> recent"

For `hackerone_hacktivity_search` and `github_repo_search`, pass the canonical bug class only.

## Reference: load SOURCES.md

If you need help with source-quality heuristics or freshness-vs-depth tradeoffs beyond what's documented here, call `read_skill_reference("intelligent_research", "SOURCES.md")`.
