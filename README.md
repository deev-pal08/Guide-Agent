# Guide Agent

Hyper-specific bug-class mastery agent. Drills a single security bug class through 5 phases — `learn → examples → practice → execute → research` — under your authority. Complements the Planner Agent (which handles general career growth) by focusing deeply on making you the world expert at specific bug classes.

## How it works

You tell `guide` what bug class to work on. It proposes options based on your state. You iterate freely until you're happy. Only then does it spend tokens on research, build a hyper-specific plan, and email it to you.

```
You:   guide postmessage
Guide: "PostMessage — new bug class. Suggested options:
          1. Learn phase — drain HackTricks, PortSwigger Academy, OWASP guides
          2. Treat as a parent class (enumerate sub-classes)
          3. Free choice — describe what you want
        Pick a number or describe what you want."
You:   "1, 3 hours"
[NOW it spends tokens — agent loop runs web_search + verify_url, builds plan, emails]
```

## The 5 phases

| Phase | What it does | Task types |
|---|---|---|
| **learn** | Drain ALL foundational theory from 30 hardcoded sources (HackTricks, PortSwigger Academy, OWASP guides, MDN, AI/cloud/mobile/binary/crypto/web3 specialized knowledge bases) | `read, course, research` |
| **examples** | Read 100s of real-world reports from 14 sources (HackerOne Hacktivity, reddelexc archive, Pentester Land, Orange Tsai blog, Embrace The Red, Project Zero, Sonar Research, PortSwigger Research, CTFsearch) | `read, research` |
| **practice** | Hands-on labs/CTFs/code review from 59 sources across web/API/AI/Web3/cloud/binary/crypto/mobile/AD/IaC. Strict litmus test: user DOES, not reads | `lab, ctf, code_review` |
| **execute** | EXACTLY 3 tasks per run — live bug-bounty hunting, OSS CVE hunting, active CTFs/hackathons — plus a Tools Section listing openly-available hunting tools | `bug_bounty, ctf` |
| **research** | Three sub-modes: gap analysis (find what nobody's published), bypass hunting (find weaknesses in defenses), draft generation (blog/talk/paper). Tool building + OSS contribution live here too | `research, write, build` |

## Resource bundle shape

Every task with 2+ URLs renders as a primary anchor + a clickable `resources` list with per-resource notes (bounty amounts, severity, what makes each one distinctive). No URLs hidden in prose.

The **execute phase** additionally ships a separate **Tools Section** — 5-10 openly-available tools you can download and use for hunting (FrogPost, DOM Invader, postMessage-tracker, etc.).

## Skills architecture

Each phase is a file-based skill (`SKILL.md` + reference docs) with progressive disclosure:

- **Level 1** (always loaded): SKILL.md frontmatter — what each skill does, when to use it
- **Level 2** (loaded when phase fires): SKILL.md body — full methodology for the active phase
- **Level 3** (loaded on demand via `read_skill_reference` tool): REFERENCES.md, GAP_ANALYSIS.md, etc. — deeper methodology only when the model genuinely needs it

Edit any `SKILL.md` directly to tune behavior without touching Python.

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
guide <bug-class> --done                # mark mastered
guide <bug-class> --resume              # un-master to revisit
guide status                            # all bug classes + phase progress + token usage
guide complete <task_id> [-h N -l "..."]
guide skip <task_id> -r "reason"
guide process-replies                   # parse email replies, update state
guide init                              # first-run wizard
```

## Architecture highlights

- **Three model tiers**: Haiku for the cheap propose/iterate conversation, Sonnet for daily plan generation, **Opus** for the research phase
- **Public Anthropic API pinned** — bypasses any shell-set `ANTHROPIC_BASE_URL` so guide-agent always hits the canonical API regardless of environment
- **Multi-source web search** in parallel: Brave + Tavily + Exa, deduplicated by URL
- **Newsletter integration** (read-only) — pulls postMessage / SSRF / whatever-bug-class articles from your Newsletter Agent's SQLite DB
- **Goal-agnostic prompts** — zero career-goal / visa / promotion mentions anywhere. Guide stays in its lane (bug-class mastery)
- **Consumed-resources ledger** — URLs assigned in past plans are never re-suggested
- **Cross-class awareness** — agent sees other mastered classes and skips overlapping basics

## State (SQLite)

All state lives in `data/guide.db` (auto-migrated on startup):

- `bug_classes` — N-level hierarchical, in_progress / mastered
- `phase_progress` — resources consumed per (bug_class, phase)
- `plans` — proposed/confirmed/sent, with rationale + tools_section
- `tasks` — with full resources list + primary anchor
- `consumed_resources` — every URL ever assigned, deduplicated
- `feedback_log` — every reply (email or CLI) with notes + learnings
- `user_notes` — persistent free-form notes from email replies (preserve registrations etc.)
- `meta` — per-brain token usage + misc

## Quick start

```bash
# 1. Install
git clone https://github.com/deev-pal08/Guide-Agent.git guide-agent
cd guide-agent
uv sync

# 2. Configure
cp config.example.yaml config.yaml      # Edit sources, email, IMAP, newsletter path
cp .env.example .env                    # Fill in API keys
# Optional: symlink AboutMe.md from planner-agent so the user profile stays in sync

# 3. First-run wizard
uv run guide init

# 4. Start drilling
uv run guide postmessage
```

## Environment variables

- `ANTHROPIC_API_KEY` — required
- `RESEND_API_KEY` — required if email enabled
- `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY` — web search (at least one needed for live discovery)
- `IMAP_EMAIL`, `IMAP_PASSWORD` — required if IMAP enabled

## Testing

```bash
uv run pytest tests/                    # 103 tests
uv run ruff check src/                  # lint
```

## Status

Day 0 — first end-to-end runs verified for postMessage across all 5 phases.

## License

MIT
