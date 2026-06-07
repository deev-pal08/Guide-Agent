# Guide Agent

Hyper-specific bug-class mastery agent. Drills a single security bug class through 5 phases — `learn → examples → practice → execute → research` — under your authority. Complements the Planner Agent (which handles general career growth) by focusing deeply on making you the world expert at specific bug classes.

## How it works

You tell `guide` what bug class to work on. It proposes options based on your state. You iterate freely until you're happy. On confirm, the CLI **pre-warms a local SQLite cache** with every URL it can find across 13 tools (HackerOne hacktivity, Pentester Land, CTFsearch, Code Review Lab, blog feeds, sitemaps, CTFtime, GitHub Search, etc.), tagged with the bug class. Then the planner reads from the DB, builds a hyper-specific plan, and emails it to you.

```
You:   guide postmessage
Guide: "PostMessage — new bug class. Suggested options:
          1. Learn phase — drain HackTricks, PortSwigger Academy, OWASP guides
          2. Treat as a parent class (enumerate sub-classes)
          3. Free choice — describe what you want
        Pick a number or describe what you want."
You:   "1, 3 hours"
[CLI: Haiku expansion call → fan-out fetch → planner reads DB → email]
```

## The 5 phases

| Phase | What it does | Task types |
|---|---|---|
| **learn** | Drain ALL foundational theory from authoritative sources — HackTricks / PortSwigger Academy / OWASP / MDN / Snyk Learn — via sitemap walking + blog feeds + web search | `read, course, research` |
| **examples** | Read 100s of real-world reports from HackerOne hacktivity (filtered by severity + bounty), Pentester Land (6.4k structured writeups), CTFsearch (35.8k CTF walkthroughs), Code Review Lab (205 source-review challenges), and research blogs (Orange Tsai, Embrace The Red, Project Zero, PortSwigger Research, Sonar, Intigriti) | `read, research` |
| **practice** | Hands-on labs/CTFs/code review — PortSwigger Labs, PentesterLab Exercises, Juice Shop, Hacker101 sessions, Code Review Lab challenges, plus platform-targeted searches for TryHackMe / HackTheBox / picoCTF rooms. Strict litmus test: user DOES, not reads | `lab, ctf, code_review` |
| **execute** | EXACTLY 3 tasks per run + a separate Tools Section. Task 1: live bug bounty programs (smart-prioritized by past bounty signal). Task 2: popular OSS projects to audit for CVEs (5000+ stars, AMBIENT). Task 3: upcoming CTFs / hackathons from CTFtime + platform queries (AMBIENT). Plus a Tools Section with 5-10 openly-available hunting tools for the current bug class | `bug_bounty, ctf` |
| **research** | Three sub-modes: gap analysis (find what nobody's published), bypass hunting (find weaknesses in defenses), draft generation (blog/talk/paper). Tool building + OSS contribution live here too | `research, write, build` |

## Prefetch-first architecture

Before every phase invocation, the CLI fans out **per bug class** across every applicable source for that phase, dedupes by URL, and writes results into a local SQLite cache tagged with the bug class. The planner then reads from the cache instead of burning tokens on live discovery.

Auto-rerun fan-out when:
- DB has 0 unread rows for this bug class
- You pass `--fresh` flag

This means: **first run of any bug class** pays for the fan-out (~12-30s, free APIs); **subsequent runs of the same class** read from DB instantly until you've drained everything.

LLM-driven synonym expansion (one Haiku call per class lifetime, ~$0.0003) turns the bare bug class name into 6-10 search terms for richer recall on technique-class searches (postMessage → window.postMessage / cross-window communication / targetorigin / etc.).

## 13 tools wired into the planner

**Local DB:** `prefetched_resource_search`, `search_consumed_resources`, `newsletter_query`
**Structured APIs:** `hackerone_hacktivity_search` (GraphQL, server-side severity + bounty filter), `pentesterland_search`, `ctfsearch_search`, `codereviewlab_search`, `ctftime_events`, `github_repos_by_stars`, `github_repo_search` (Git Tree walker)
**Generic webcrawl:** `blog_feed_search` (RSS+Atom), `sitemap_search` (handles sitemap indexes + path-only matching), `web_search` (Brave + Tavily + Exa in parallel)
**Verification:** `verify_url`

## Resource bundle shape

Every task with 2+ URLs renders as a primary anchor + a clickable `resources` list with per-resource notes (bounty amounts, severity, stars, language, what makes each one distinctive). No URLs hidden in prose.

The **execute phase** additionally ships a separate **Tools Section** — 5-10 openly-available tools you can download and use for hunting (FrogPost, DOM Invader, postMessage-tracker, xss-payloads, etc.).

## Skills architecture

Each phase is a file-based skill (`SKILL.md` + reference docs) with progressive disclosure:

- **Level 1** (always loaded): SKILL.md frontmatter — what each skill does
- **Level 2** (loaded when phase fires): SKILL.md body — full methodology for the active phase
- **Level 3** (loaded on demand via `read_skill_reference` tool): REFERENCES.md, GAP_ANALYSIS.md, etc.

Edit any `SKILL.md` directly to tune behavior without touching Python. All 5 phase skills + the `intelligent_research` skill are aligned with the current 13-tool wiring.

## Key commands

```bash
guide <bug-class>                       # propose options (cheap, no tools fired)
guide <bug-class> --learn               # skip propose, go straight to learn phase
guide <bug-class> --examples
guide <bug-class> --practice
guide <bug-class> --execute
guide <bug-class> --research            # default sub-mode: gap_analysis
guide <bug-class> --research --research-mode bypass_hunting
guide <bug-class> --hours N             # override default 3h target
guide <bug-class> --no-email            # print plan to terminal only
guide <bug-class> --fresh               # bypass DB cache, force live fan-out
guide <bug-class> --done                # mark mastered
guide <bug-class> --resume              # un-master to revisit
guide populate <bug-class> [--phase=examples]   # pre-warm DB without firing planner
guide expansions <bug-class>            # show / refresh / edit synonym cache
guide status                            # all classes + phase progress + token usage
guide complete <task_id> [-h N -l "..."]
guide skip <task_id> -r "reason"
guide process-replies                   # parse email replies, update state
guide init                              # first-run wizard
```

## Architecture highlights

- **Three model tiers**: Haiku for the cheap propose/iterate + synonym expansion, Sonnet for daily plan generation, **Opus** for the research phase
- **Public Anthropic API pinned** — bypasses any shell-set `ANTHROPIC_BASE_URL`
- **Multi-source web search** in parallel: Brave + Tavily + Exa, dedup by URL
- **Per-bug-class fan-out** writes to local SQLite cache; planner reads instantly on subsequent runs
- **LLM synonym expansion** (cached forever per class) — solves recall gap for technique-classes (postMessage, request smuggling, prototype pollution)
- **Phase-aware adapter gating** — only run sources that fit the phase intent (e.g., no hacktivity for learn, no writeups for practice)
- **Consumed-resources ledger** — URLs assigned in past plans are never re-suggested
- **Cross-class awareness** — agent sees other mastered classes and skips overlapping basics
- **Goal-agnostic prompts** — zero career-goal / visa / promotion mentions anywhere

## State (SQLite)

All state lives in `data/guide.db` (auto-migrated on startup):

- `bug_classes` — N-level hierarchical, in_progress / mastered
- `phase_progress` — resources consumed per (bug_class, phase)
- `plans` — proposed/confirmed/sent, with rationale + tools_section
- `tasks` — with full resources list + primary anchor
- `consumed_resources` — every URL ever assigned, deduplicated
- `feedback_log` — every reply (email or CLI) with notes + learnings
- `user_notes` — persistent free-form notes from email replies
- `prefetched_resources` — local URL cache from fan-out (per-source provenance)
- `resource_tags` — `(resource_id, bug_class)` mapping; one URL can be tagged for multiple classes
- `bug_class_expansions` — cached Haiku synonym list per bug class
- `bug_class_tag_scans` — markers for legacy lazy-tag scans
- `meta` — per-brain token usage + misc

## Quick start

```bash
# 1. Install
git clone https://github.com/deev-pal08/Guide-Agent.git guide-agent
cd guide-agent
uv sync

# 2. Configure
cp config.example.yaml config.yaml      # Edit sources, email, IMAP, newsletter path
cp .env.example .env                    # Fill in API keys (esp. GITHUB_TOKEN — see below)

# 3. First-run wizard
uv run guide init

# 4. Start drilling
uv run guide postmessage
```

## Environment variables

- `ANTHROPIC_API_KEY` — required
- `RESEND_API_KEY` — required if email enabled
- `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY` — web search (at least one needed)
- `GITHUB_TOKEN` — **strongly recommended.** Without it, GitHub Search + Tree API rate-limits hit fast (60 req/hr unauthenticated vs 5000+ req/hr authenticated). A classic PAT with **no scopes** is enough for public repo reads.
- `IMAP_EMAIL`, `IMAP_PASSWORD` — required if IMAP enabled

## Testing

```bash
uv run pytest tests/                    # 323 tests
uv run ruff check src/                  # lint
```

## Day 0 live-tested XSS phase output

| Phase | URLs in DB after fan-out |
|---|---|
| learn | 93 |
| examples | 3,300 (including 451 high+critical hacktivity reports) |
| practice | 535 |
| execute | ~230 (74 popular OSS + 22 CTFs + 100+ web + 8 hubs + 30 hunting tools) |

## License

MIT
