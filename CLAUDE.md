# Guide Agent

## Project Overview
Hyper-specific bug-class mastery agent. Drills a SINGLE security bug class (e.g., postMessage, prototype pollution) through 5 user-controlled phases. Complements the Planner Agent (general career growth) by focusing deeply on world-expert mastery of specific bug classes.

User's stated philosophy: *"What I have always done in the past and have always worked for me and every single person of this world in security is mastering a group of bug classes and being the world expert at that."*

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) — Haiku for conversation + expansion, Sonnet for daily plans, Opus for research phase
- **Public Anthropic API pinned** in `agent/base.py` (`base_url="https://api.anthropic.com"`) — bypasses any shell-set `ANTHROPIC_BASE_URL`
- Resend API for outbound briefing emails
- IMAP (stdlib) for inbound feedback via email replies
- Click for CLI
- Pydantic for config + models
- SQLite for state with idempotent migrations
- tenacity for API retry
- httpx for all live fetches (web search, GraphQL, sitemaps, feeds, github)
- Goal-agnostic: zero career-goal / visa / promotion mentions in any prompt

## Authority Model — Conversational
1. User runs `guide <bug-class>` or `guide <bug-class> --<phase>`
2. Conversation agent (Haiku, NO tools, ~$0.001) reads state and proposes options
3. User iterates freely in natural language until satisfied
4. On confirm, the CLI pre-warms the DB:
   - `ensure_expansion(bug_class)` — one-time Haiku call (~$0.0003) caches synonym list
   - `populate_if_empty()` — fans out across all phase-appropriate sources if DB has no unread rows OR `--fresh` flag set
5. Then planner (Sonnet) — or researcher (Opus) — runs against the populated DB
6. Email sent (HH:MM timestamp in subject so Gmail doesn't thread same-day re-runs), state updated

## Prefetch-First Architecture (THE core design)
Before every phase invocation, the CLI fans out **per bug class** across every applicable source, dedupes by URL, and writes results into the `prefetched_resources` table tagged with the bug class. The planner then reads from the DB instead of burning tokens on live discovery.

**Auto-trigger rules** (`populate_if_empty`):
- DB has 0 unread rows for this `(bug_class)` → fan-out fires
- `--fresh` flag set → fan-out fires regardless
- Otherwise → DB-only, instant

**Per-class scoping** — same DB, but each row is tagged with the bug class it was fetched for. Two classes can share URLs (one insert into `prefetched_resources`, two tags in `resource_tags`).

**LLM-driven synonym expansion (Lever 3)** — `ensure_expansion(bug_class)` makes ONE Haiku call to produce 6-10 search synonyms (e.g. `postmessage` → `[postmessage, window.postmessage, cross-window communication, targetorigin, postmessage xss, ...]`). Cached forever per class. Passed to all expansion-aware adapters.

## 13 Tools (by category)

### Discovery — local DB
| Tool | What |
|---|---|
| `prefetched_resource_search` | Query the prefetched DB tagged for current bug class, auto-excludes consumed URLs |
| `search_consumed_resources` | Check which URLs the user has already drained |
| `newsletter_query` | Query the Newsletter Agent's SQLite DB (read-only) |

### Discovery — structured APIs
| Tool | What |
|---|---|
| `hackerone_hacktivity_search` | HackerOne GraphQL, structured filter by severity + bounty, sorted server-side |
| `pentesterland_search` | Pentester Land writeups.json (6.4k entries, tagged by Bugs[] array, sorted by bounty) |
| `ctfsearch_search` | HackMap CTF writeup index via Typesense (35.8k indexed writeups, full-text search) |
| `codereviewlab_search` | Code Review Lab public API (205 source-review challenges by vulnType + language + difficulty) |
| `ctftime_events` | CTFtime API for upcoming/ongoing CTFs (weight, format, restrictions metadata) |
| `github_repos_by_stars` | GitHub Search API sorted by stars (popular OSS targets + hunting tools) |
| `github_repo_search` | Walk a public repo's Git Tree (curated bug-class folders in PayloadsAllTheThings etc.) |

### Discovery — generic webcrawl helpers
| Tool | What |
|---|---|
| `blog_feed_search` | Generic RSS/Atom feed parser (stdlib XML, handles Blogger pagination), supports `|`-OR synonyms |
| `sitemap_search` | Generic sitemap.xml walker (follows sitemap indexes, path-only matching to avoid host substring false positives) |
| `web_search` | Brave + Tavily + Exa in parallel, dedup by URL |

### Verification + read-skill
- `verify_url` — HTTP HEAD/GET, returns page_title, drops non-2xx
- `read_skill_reference` — load Level-3 skill methodology files on demand

## 5-Phase Loop (user-invoked)

| Phase | Adapters that fire | Special notes |
|---|---|---|
| **learn** | web_search, sitemap_search, blog_feed_search, github_repo_search (curated docs only) | Theory only — no labs, no writeups |
| **examples** | hacktivity, pentesterland, ctfsearch, codereviewlab, sitemap_search, blog_feed_search, github_repo_search (curated archives), web_search | Real-world reports + writeups; bug-class scoped |
| **practice** | ctfsearch, codereviewlab, sitemap_search, blog_feed_search, github_repo_search (vulnerable apps `.md` only), web_search (with platform queries for THM/HTB/picoCTF) | User DOES not READS |
| **execute** | popular_oss (github_repos_by_stars), ctftime, hunting_tools (github_repos_by_stars with bug-class queries), web_search (CTF-platform queries), hardcoded_hubs (HTB/picoCTF/THM bare URLs) | AMBIENT discovery — bug class NOT a filter for OSS / CTF / programs; only used for hunting tools |
| **research** | NONE — discovery-only via web_search | gap_analysis / bypass_hunting / draft_generation sub-modes |

## Execute Phase — strict 3-task structure + Tools Section
- **Task 1** — Live bug bounty programs (smart-prioritized by past bounty signal for current bug class)
- **Task 2** — Popular OSS projects to audit for CVEs (AMBIENT, 5000+ stars, language-spread)
- **Task 3** — Upcoming CTFs / hackathons / competitions (AMBIENT, CTFtime + platform queries)
- **`tools_section`** field — separate green block in email, 5-10 openly-available tools for current bug class (FrogPost, DOM Invader, xss-payloads, etc.)

## Resource Bundle Shape (Task 2+ URLs)
Every task has a primary anchor URL plus a `resources` list of `{url, name, note}` entries. Notes carry per-resource context (bounty amounts, severity, stars, language, what makes it distinctive). NEVER inline URLs in prose — renderer only shows what's in the resources array.

## Skills Architecture (file-based, progressive disclosure)
NOT Anthropic API Skills (those run sandboxed, no network). File-based SKILL.md bundles with our own loader.

```
src/guide_agent/skills/
├── loader.py                     # Reads SKILL.md, exposes read_skill_reference tool
├── learn/{SKILL.md, REFERENCES.md}
├── examples/{SKILL.md, REFERENCES.md}
├── practice/{SKILL.md, REFERENCES.md}
├── execute/{SKILL.md, REFERENCES.md}
├── research/{SKILL.md, GAP_ANALYSIS.md, BYPASS_HUNTING.md, DRAFT_GENERATION.md}
└── intelligent_research/{SKILL.md, SOURCES.md}
```

Loading model:
- **Level 1** (always loaded): SKILL.md frontmatter, ~100 tokens
- **Level 2** (loaded when phase fires): SKILL.md body
- **Level 3** (loaded on demand via tool): REFERENCES.md, GAP_ANALYSIS.md, etc.

All SKILL.md files are aligned with current tooling (prefetch-first + live fallback tool names).

## Bug Class Taxonomy
- User-defined, N-level hierarchical (`bug_classes.parent_id` self-FK)
- Per-class state: in_progress / mastered, phase progress, consumed_resources ledger
- Mastery is explicit only (`guide <class> --done`); can resume to revisit

## Project Structure
```
src/guide_agent/
├── cli.py                              # Click commands + auto-trigger populate_if_empty
├── config.py                           # Pydantic config; SourceConfig has feed_url + sitemap_url
├── models.py                           # Phase, Task, Resource, Plan, etc.
├── refresh.py                          # Per-bug-class fan-out + phase-aware source flags + per-phase web query templates
├── agent/
│   ├── base.py                         # Shared client + retry + JSON parsing; pins public API
│   ├── conversation.py                 # Cheap propose/iterate loop
│   ├── planner.py                      # Sonnet — fires after confirmation, all 13 tools wired
│   ├── researcher.py                   # Opus — research phase with sub-mode reference loading
│   ├── expansion.py                    # Haiku-cheap LLM synonym expansion (Lever 3)
│   ├── feedback.py                     # Email reply parser
│   └── tools.py                        # All 13 tools + helpers
├── skills/                             # SKILL.md bundles (see above)
├── sources/
│   ├── hardcoded.py                    # Pool renderer + feed_url/sitemap_url surfacing + deep_urls
│   ├── newsletter.py                   # Read-only newsletter DB query
│   └── web.py                          # Provider availability summary
├── state/store.py                      # SQLite — bug_classes, phase_progress, plans, tasks, consumed_resources, feedback_log, user_notes, meta, prefetched_resources, resource_tags, bug_class_expansions, bug_class_tag_scans
└── email/{sender,receiver,templates}.py # Resend + IMAP + dark-themed HTML with resources + tools_section
```

## Key Commands
```bash
uv run guide <bug-class>                # propose options (cheap, no tools)
uv run guide <bug-class> --<phase>      # skip propose, fire phase immediately
uv run guide <bug-class> --research --research-mode gap_analysis|bypass_hunting|draft_generation
uv run guide <bug-class> --hours N      # override default 3h target
uv run guide <bug-class> --no-email     # print plan to terminal only
uv run guide <bug-class> --fresh        # bypass DB cache, force live fan-out
uv run guide <bug-class> --done         # mark mastered
uv run guide <bug-class> --resume       # un-master
uv run guide populate <bug-class> [--phase=examples]   # pre-warm DB without firing planner
uv run guide expansions <bug-class>     # show / refresh / edit synonym cache
uv run guide status                     # all classes + phases + token usage
uv run guide complete <task_id> [--hours N --learnings "..."]
uv run guide skip <task_id> -r "reason"
uv run guide process-replies            # parse IMAP replies, update state
uv run guide init                       # first-run wizard
uv run pytest tests/                    # 323 tests
uv run ruff check src/
```

## Environment Variables
- `ANTHROPIC_API_KEY` — required
- `RESEND_API_KEY` — required if email enabled
- `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY` — web search (at least one required)
- `GITHUB_TOKEN` — **strongly recommended** (60 req/hr → 5000 req/hr); without it, github fan-out is rate-limited fast
- `IMAP_EMAIL`, `IMAP_PASSWORD` — required if IMAP enabled

## Token Limits
- Planner output `max_tokens=32768` (2× safety headroom; plan JSON is ~2k)
- Conversation brain `max_tokens=2048`
- Expansion brain `max_tokens=512`
- Input context: 200k window (handles 24k of tool results easily)

## Coordination with Planner Agent
NONE intentional. Planner handles general career growth. Guide handles deep bug-class mastery. Guide DOES read the Newsletter Agent's SQLite DB but writes nothing to it.

## Testing Status
**323 tests passing, lint-clean.** Coverage across all tools, refresh adapters, expansion cache, store layer, email rendering, skill loader, feedback parser, conversation brain.

## Live-Tested XSS Phase Output (Day 0)
| Phase | URLs in DB after fan-out |
|---|---|
| learn | 93 |
| examples | 3,300 (including 451 high+critical hacktivity reports) |
| practice | 535 |
| execute | ~230 (74 popular OSS + 22 CTFs + 100+ web + 8 hubs + 30 hunting tools) |

## Status
Day 0 — fully aligned skills, all 13 tools wired, prefetch + expansion model live-tested across all 5 phases.
