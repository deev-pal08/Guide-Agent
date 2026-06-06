---
name: examples
description: Read EXTENSIVE real-world reports and case studies for a single bug class — bug bounty writeups, CVE analyses, HackerOne Hacktivity, blog posts, conference case studies, empirical research papers. Goal is dozens of reports per topic to internalize how the attack manifests in production. NO labs, NO theory — only real-world examples.
---

# Examples Phase

## Mission
The user has DRAINED foundational theory in the learn phase. Now they need to internalize how the bug class actually manifests in real software, in real bounty programs, in real CVEs — under real constraints (filters, partial defenses, exotic stacks, real-world adversarial settings). Goal: dozens of reports per topic so the user can recognize the attack pattern in any codebase by sight.

This phase is **real-world reports only**. No theory (already drained). No labs (next phase). No production execution (the phase after that).

## Inputs
Same as the learn phase — bug class, target hours, consumed resources, mastered classes, recent feedback, user notes.

## Sources you mine

**Hardcoded pool (per config):** HackerOne Hacktivity, GitHub Security Advisories, Pentester Land Bug Bounty Writeups.

**Newsletter DB:** the user's newsletter agent has been collecting security writeups continuously. Call `newsletter_query` with the bug class name and 3-5 sub-area keywords. This is your HIGHEST-VALUE source for the examples phase — the newsletter agent has already done the curation work.

**Web search:** for any gaps after newsletter + hardcoded. Look for:
- HackerOne disclosed reports (`site:hackerone.com/reports` + bug class)
- Bugcrowd disclosures
- CVE analysis blog posts with PoC walkthroughs
- Medium / blog post writeups from recognized hunters
- Conference talk case studies (DEF CON, BSides, OWASP Global AppSec, BlackHat)
- Empirical research papers that ANALYZE real applications (NOT the foundational/taxonomy papers — those were learn-phase)
- Incident post-mortems

## Tool loop

1. **`search_consumed_resources`** — drop already-read URLs.
2. **`newsletter_query`** FIRST (more curated, cheaper than web) + **`web_search`** for gaps, BOTH batched into ONE turn. Vary the queries by sub-area: e.g., for postMessage: `["postMessage hackerone disclosed", "postMessage CVE writeup origin bypass", "postMessage iframe sandbox bypass real world", "postMessage data leak production"]`.
3. **`verify_url`** in ONE turn on every candidate.
4. **(optional)** `read_skill_reference("examples", "REFERENCES.md")` for methodology depth.
5. **Final turn** — emit Plan JSON.

## Ambition rule — VOLUME is the point in examples phase
The user wants DOZENS of reports per topic. ONE task = "read 15-20 reports on a single sub-area in one sitting and extract patterns" — not "read one report at a time."

**Bad task:**
- "Read this one HackerOne report on postMessage (0.25h)"

**Good task:**
- "Read 18 disclosed HackerOne postMessage reports in one sitting (2.5h). Group by failure mode (origin not checked, origin partial match, postMessage data deserialization, message handler exposed to wrong frame). For each group, write 2 bullet points on (a) the developer mistake, (b) the attacker primitive. Output: a markdown table of failure modes you can reference later."

A good plan in the examples phase usually has 1-3 batched-volume tasks totaling ~target_hours.

## Task-type rules
- ALL tasks MUST have `task_type` in `{read, research}`. No labs. No CTFs.
- `read` for digesting writeups individually or in a batch.
- `research` when the task involves synthesizing patterns across many reports (which it usually does in this phase).

## When to call read_skill_reference
- If you need help judging report quality (HackerOne low-signal noise vs high-signal case studies) → `read_skill_reference("examples", "REFERENCES.md")`.
- If you're unsure how to group reports for batching → load REFERENCES.md.

## Completion signals (when to suggest advancing to practice)
- Phase progress shows 30+ reports consumed for this bug class
- Recent feedback shows the user can predict attack patterns before reading the writeup
- User explicitly states readiness for hands-on practice

## Output format
Strict JSON. 1-5 ambitious tasks, all batched-volume reading. NEVER assign one report at a time.
