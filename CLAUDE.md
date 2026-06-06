# Guide Agent

## Project Overview
Hyper-specific bug-class mastery agent. Drills a SINGLE security bug class (e.g., postMessage, prototype pollution) through 5 user-controlled phases. Complements the Planner Agent (general career growth) by focusing deeply on world-expert mastery of specific bug classes.

User's stated philosophy: *"What I have always done in the past and have always worked for me and every single person of this world in security is mastering a group of bug classes and being the world expert at that."*

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) — Haiku for conversation, Sonnet for daily plans, Opus for research phase
- **Public Anthropic API pinned** in `agent/base.py` (`base_url="https://api.anthropic.com"`) — bypasses any shell-set `ANTHROPIC_BASE_URL` so guide-agent always uses the canonical API regardless of environment
- Resend API for outbound briefing emails
- IMAP (stdlib) for inbound feedback via email replies
- Click for CLI
- Pydantic for config + models
- SQLite for state with idempotent migrations
- tenacity for API retry
- httpx for URL verification + web search (Brave / Tavily / Exa in parallel)
- Goal-agnostic: zero career-goal / visa / promotion mentions in any prompt — guide stays in its lane (bug-class mastery)

## Authority Model — Conversational
1. User runs `guide <bug-class>` or `guide <bug-class> --<phase>`
2. Conversation agent (Haiku, NO tools, cheap — ~$0.001 per round) reads state and proposes options
3. User iterates freely in natural language ("more practice", "harder", "drop option 2") until satisfied
4. Only when user confirms does the planner agent (Sonnet) — or researcher (Opus) for research phase — fire web_search + research and build a plan
5. Email sent (subject includes `HH:MM` timestamp so Gmail doesn't thread same-day re-runs), state updated
6. No tokens spent on research until user approves

This is the critical difference from the Planner: Guide is on-demand, conversational, user-authoritative.

## 5-Phase Loop (user-invoked, agent-suggested)

| Phase | What it does | Task types | Hardcoded sources | Discovery |
|---|---|---|---|---|
| **learn** | Drain ALL foundational theory | `read, course, research` | 30 sources (HackTricks, PortSwigger Academy, OWASP, MDN, 0xn3va, PayloadsAllTheThings, KathanP19, Snyk Learn, OWASP MASTG, AI/cloud/mobile/binary/crypto/web3 specialized) | + newsletter + web |
| **examples** | Read 100s of real-world reports | `read, research` | 14 sources (HackerOne Hacktivity, reddelexc archive, BugBountyHunting, BugBoard, Pentester Land, Orange Tsai, Embrace The Red, Project Zero, Sonar, PentesterLab Blog, PortSwigger Research, Medium, CTFsearch) | + newsletter + web |
| **practice** | Hands-on labs/CTFs (batched) — strict litmus test: user DOES not READS | `lab, ctf, code_review` | 59 sources across web/API/AI/Web3/cloud/binary/crypto/mobile/AD/IaC | + web |
| **execute** | EXACTLY 3 tasks + Tools section: live bug bounty hunting, OSS CVE hunting, active CTFs/hackathons | `bug_bounty, ctf` (NO build, NO write) | HackerOne / Bugcrowd / Intigriti / YesWeHack program directories + HTB live/upcoming/past CTFs | web discovery |
| **research** | Three sub-modes: gap analysis, bypass hunting, draft generation. Tool building + OSS contribution live HERE. | `research, write, build` | (discovery only) | web + arxiv + venue proceedings |

## Resource Bundle Shape (Task 2+ URLs)
Every task has a primary anchor URL plus a `resources` list of `{url, name, note}` entries — rendered as a clickable list in email/terminal. Notes carry per-resource context (bounty amounts, severity, what makes it distinctive). NEVER inline URLs in prose — the renderer only shows what's in the resources array.

## Execute Phase — Tools Section
Execute plans additionally carry a `tools_section` field (list of `Resource` entries) listing 5-10 openly-available tools the user can DOWNLOAD AND USE for hunting (NOT to build). Rendered as a separate green block in the email below the 3 task cards. Other phases leave this empty.

## Skills Architecture (file-based, progressive disclosure)
NOT Anthropic API Skills (those run sandboxed without network access, can't web_search). Instead: file-based SKILL.md bundles with our own loader, modeled on the Skills design pattern.

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
- **Level 1** (always loaded): SKILL.md frontmatter (name, description), ~100 tokens
- **Level 2** (loaded when phase fires): SKILL.md body, <5k tokens
- **Level 3** (loaded on demand via tool): REFERENCES.md, GAP_ANALYSIS.md, etc. — only when model invokes `read_skill_reference(phase, filename)`

SKILL.md files are editable directly — tune behavior without touching Python.

## Bug Class Taxonomy
- User-defined, N-level hierarchical (`bug_classes.parent_id` self-FK)
- Agent doesn't constrain — if user says "Client-Side Web Bugs" and it's a parent class with sub-classes, agent enumerates and asks which to pick
- If user says "postmessage" (leaf), agent starts drilling immediately
- Per-class state: in_progress / mastered, phase progress per phase, consumed_resources ledger
- Mastery is explicit only (`guide <class> --done`); can resume to revisit

## Cross-Class Awareness
When planning for active bug class, agent sees user's other mastered classes (one-line summary in prompt) so it can skip already-known basics. E.g., "User has mastered DOM XSS — skip JS sources/sinks fundamentals in postMessage learn phase."

## Hardcoded Source Pool + Deep URLs (Hybrid)
Config `sources` defines per-phase pools (base URLs). Optional `sources.deep_urls.<phase>.<bug-class>` provides explicit deep URLs the agent visits directly via verify_url, deduplicated against web_search results. Add entries over time as you discover canonical deep pages.

## Project Structure
```
src/guide_agent/
├── cli.py                              # Click commands
├── config.py                           # Pydantic config
├── models.py                           # Phase, Task, Resource, Plan, etc.
├── agent/
│   ├── base.py                         # Shared client + retry + JSON parsing
│   ├── conversation.py                 # Cheap propose/iterate loop
│   ├── planner.py                      # Sonnet — fires after confirmation
│   ├── researcher.py                   # Opus — research phase with sub-mode reference loading
│   ├── feedback.py                     # Email reply parser
│   └── tools.py                        # web_search, verify_url, newsletter_query, search_consumed_resources, read_skill_reference
├── skills/                             # SKILL.md bundles (see above)
├── sources/
│   ├── hardcoded.py                    # Pool renderer + deep_urls support
│   ├── newsletter.py                   # Read-only newsletter DB query
│   └── web.py                          # Provider availability summary
├── state/store.py                      # SQLite — bug_classes, phase_progress, plans (+ tools_section_json), tasks (+ resources_json), consumed_resources, feedback_log, user_notes, meta
└── email/{sender,receiver,templates}.py # Resend + IMAP + dark-themed HTML template with resources list + tools_section block
```

## Key Commands
```bash
uv run guide <bug-class>                # propose options (cheap, no tools)
uv run guide <bug-class> --<phase>      # skip propose, fire phase immediately
uv run guide <bug-class> --research --research-mode gap_analysis|bypass_hunting|draft_generation
uv run guide <bug-class> --hours N      # override default 3h target
uv run guide <bug-class> --no-email     # print plan to terminal only
uv run guide <bug-class> --done         # mark mastered
uv run guide <bug-class> --resume       # un-master
uv run guide status                     # all classes + phases + token usage
uv run guide complete <task_id> [--hours N --learnings "..."]
uv run guide skip <task_id> -r "reason"
uv run guide process-replies            # parse IMAP replies, update state
uv run guide init                       # first-run wizard
uv run pytest tests/                    # 103 tests
uv run ruff check src/
```

## Environment Variables
- `ANTHROPIC_API_KEY` — required
- `RESEND_API_KEY` — required if email enabled
- `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY` — web search (at least one required for live discovery)
- `IMAP_EMAIL`, `IMAP_PASSWORD` — required if IMAP enabled

## Coordination with Planner Agent
NONE intentional. Planner handles general career growth (random surprise topics, AI security drills, visa portfolio, job-switching prep). Guide handles deep bug-class mastery. User manages time conflicts themselves. Guide DOES read the Newsletter Agent's SQLite DB (same as planner) but writes nothing to it.

## Testing Status
103 tests across `test_store.py`, `test_skill_loader.py`, `test_conversation.py`, `test_feedback.py`, `test_email.py`, `test_sources.py`. Lint-clean (ruff). All phases (learn, examples, practice, execute, research) verified end-to-end against the live API.

## Status
Day 0 — first end-to-end runs complete for postMessage across all 5 phases.
