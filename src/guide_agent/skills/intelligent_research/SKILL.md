---
name: intelligent_research
description: Cross-cutting research workflow used inside every phase skill. Combines hardcoded source pool (per phase from config) + newsletter DB query + multi-source web search (Brave/Tavily/Exa), deduplicates, filters against consumed_resources, and ranks by relevance to the active bug class. Phase skills call into this — never called directly by the user.
---

# Intelligent Research

This is the shared discovery workflow that every phase skill uses. The phase skill decides WHAT to search for (informed by phase semantics). This skill describes HOW to combine the three source pools efficiently.

## Three pools, one ranked list

1. **Hardcoded pool** (per-phase, from config.yaml). Authoritative knowledge bases the user has explicitly chosen. Filter these pools for material related to the active bug class.
2. **Newsletter DB** (user's curated article store). High signal because it's been pre-filtered by the newsletter agent. Use `newsletter_query` with the bug class + 3-5 sub-area keywords.
3. **Web search** (Brave + Tavily + Exa in parallel via `web_search`). The fallback for what the curated sources don't cover. Use varied queries.

## Pool prioritization by phase

- **learn phase:** hardcoded ≥ web > newsletter (theory tends to live in authoritative knowledge bases more than in newsletters)
- **examples phase:** newsletter > web ≥ hardcoded (newsletters are the user's curated case-study store)
- **practice phase:** hardcoded > web > newsletter (labs come from a small set of well-known platforms)
- **execute phase:** web > newsletter > hardcoded (live programs / CTFs are discovery-only — no hardcoded pool)
- **research phase:** web (academic-biased) > newsletter > hardcoded (original work needs primary sources)

## Workflow inside a phase agent loop

1. Call `search_consumed_resources` to know what's already covered.
2. Call `newsletter_query` AND `web_search` IN ONE TURN. Batch all queries.
3. Merge results, deduplicate by exact URL match. Drop already-consumed.
4. Call `verify_url` on every candidate IN ONE TURN.
5. Use the returned `page_title` as the resource_name in the final plan.
6. Drop candidates that failed verification (non-2xx, error).

## Deduplication rules

- Exact URL match → keep one (prefer the one with a verified title).
- Same domain + same path → keep one.
- Same canonical title (e.g., two blog posts with identical titles) → keep the newer one.
- A summary article and the original it summarizes → keep the original (higher signal).

## Ranking heuristics

Within the merged candidate list, prioritize:

1. **Recency** for examples/practice/execute/research phases. Bug bounty writeups from 2024-2026 are far more useful than 2018 — bug classes evolve. EXCEPTION: foundational learn-phase material is timeless (the OWASP cheat sheet doesn't need to be from this year).
2. **Authority of source.** Original spec > recognized researcher's blog > aggregator > AI-generated content farm.
3. **Match score from newsletter_query** (when relevant). Higher score = stronger keyword overlap with the bug class.
4. **Topic depth.** A 500-word skim is lower-priority than a 5000-word deep dive on the same topic.

## Query construction

For each phase, vary queries along several dimensions:

- **Sub-area variations** — "postMessage origin validation", "postMessage data deserialization", "postMessage iframe sandbox bypass"
- **Source-type variations** — "<bug class> hackerone disclosed report", "<bug class> CVE writeup", "<bug class> arxiv paper", "<bug class> conference talk slides"
- **Stack variations** — "<bug class> React", "<bug class> Node.js", "<bug class> Spring Boot"
- **Temporal variations** — "<bug class> 2025", "<bug class> recent", "<bug class> new technique"

Aim for 3-5 varied queries per turn. Batch them all in one tool-use turn — never spread across multiple turns.

## Reference: load SOURCES.md
If you need help with source-quality heuristics or freshness-vs-depth tradeoffs beyond what's documented here, call `read_skill_reference("intelligent_research", "SOURCES.md")`.
