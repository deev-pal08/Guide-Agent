---
name: execute
description: Hunt for real findings on real targets. EXACTLY 3 tasks per run — Task 1 bug-bounty hunting on live programs, Task 2 OSS CVE hunting on popular open-source projects, Task 3 active CTFs / hackathons / competitions. Plus a Tools Section listing openly-available tools for the bug class. NO building, NO writing, NO reading — pure execution. Tool building and open-source contribution belong to the research phase.
---

# Execute Phase

## Mission
The user has drained theory (learn), absorbed real-world patterns (examples), and built muscle memory through hands-on practice. Execute is where they HUNT — on live bug bounty programs, on popular open-source projects, and in active CTFs/competitions. Every output is something the user actually attacks; nothing in this phase is theoretical, instructional, or constructive.

## STRICT STRUCTURE — exactly 3 tasks + 1 tools section per run

Every execute plan has EXACTLY THREE tasks, in this order:

### Task 1 — Bug Bounty Hunting (task_type=bug_bounty)
3-5 distinct LIVE bug-bounty programs the user can hunt this bug class on TODAY.
Each resource = a specific program page (not a platform homepage) with the bug class confirmed in scope.

### Task 2 — Open Source CVE Hunting (task_type=bug_bounty)
3-5 distinct POPULAR open-source projects the user can audit for this bug class, with realistic CVE potential.
Each resource = a specific repo with concrete attack surface for the bug class. Popularity floor enforced (see below).

### Task 3 — Active CTFs / Hackathons / Competitions (task_type=ctf)
3-5 distinct LIVE OR UPCOMING events (deadline / start date within the next 30-60 days) where the bug class is likely to appear in challenges.
Each resource = a specific event page with a date and registration/participation info.

If any category genuinely has no good options for this bug class, output an empty `resources: []` for that task but KEEP THE TASK SHELL (so the structure is always 3 tasks). Mention in the rationale why that category is empty.

### Tools Section (NOT a task — separate `tools_section` field on the Plan)
5-10 openly-available tools the user can USE for hunting this bug class. These are tools to download/run, not tools to build.
For example for postMessage: FrogPost (Chrome extension), DOM Invader (Burp), postMessage fuzzers on GitHub, browser DevTools helpers.

## Popularity floor for OSS targets (Task 2)
Every OSS project in Task 2 MUST meet AT LEAST ONE of:
- 10,000+ GitHub stars
- Top 1% download count on its package ecosystem (npm, PyPI, Maven, Crates.io, RubyGems, Go modules)
- Used by a recognizable company (mentioned in major-company package.json, gemfile, requirements.txt, etc.)
- Active maintenance: last commit within 6 months AND >1k stars

If a candidate doesn't meet ONE of these, drop it. A CVE in `lodash` matters; a CVE in a hobby project doesn't.

For each OSS target's `note` field, cite the popularity signal explicitly (e.g. `"260k weekly npm downloads"`, `"32k stars, used by Vercel"`).

## CTF / hackathon / competition discovery (Task 3)
Bias toward:
- Specific named events with a public registration / event page
- Deadline or event start within the next 30-60 days
- Bug class is plausibly relevant (web bugs → web CTFs, smart contract bugs → DeFi CTFs, etc.)
- Open to individual participants (skip invite-only or corporate-only events)

Sources to search:
- CTFtime upcoming events
- HackTheBox Live + Upcoming CTF event pages (hardcoded pool)
- Specific named CTFs: picoCTF, Google CTF, DEF CON CTF qualifiers, BSides CTFs, Pwn2Own, AI-red-teaming competitions
- Public hackathon platforms (Devpost, MLH for student events) — only when bug-class-relevant
- Bug-class-specific competitions (e.g., AI security CTFs from Lakera, Wiz, etc.)

## Sources you mine — HARDCODED HUBS + DISCOVERY

The execute phase has a hardcoded pool of bug-bounty platform directories and CTF event hubs. Everything else comes from live discovery.

**Hardcoded hubs to mine first** (use `site:`-scoped searches against each):
- HackerOne programs directory + Hacktivity
- Bugcrowd / Intigriti / YesWeHack program directories
- HackTheBox live / upcoming / past CTF event listings

**Web search** for everything else:

**For Task 1 — bug-bounty programs:**
- `"<bug-class>" bug bounty program in-scope`
- `"<bug-class>" responsible disclosure`
- `vendor bug bounty program <bug-class>`
- `site:hackerone.com/<program-slug>` for specific candidates
- Cross-reference past disclosed reports — if Shopify paid $3000 for a postMessage XSS, similar SaaS programs are good targets

**For Task 2 — popular OSS:**
- `"<bug-class>" github stars:>10000`
- `popular npm package <bug-class>`
- `widely-used <stack> library <bug-class>`
- `"<bug-class>" production library`
- `top github repos <stack-relevant-to-bug-class>`
- For each candidate, verify popularity via npm/GitHub before including

**For Task 3 — CTFs / hackathons / competitions:**
- `"<bug-class>" CTF 2026 upcoming`
- `CTFtime upcoming <bug-class>`
- `AI security CTF 2026`
- `web security hackathon 2026 register`
- `Pwn2Own 2026 schedule`

**For the Tools Section:**
- `"<bug-class>" scanner tool github`
- `"<bug-class>" fuzzer github`
- `"<bug-class>" Burp extension`
- `"<bug-class>" Chrome extension security testing`
- `awesome <bug-class>` lists (curated tool indices)

## Tool loop

1. **`search_consumed_resources`** — skip already-targeted programs/repos/CTFs/tools.
2. **`newsletter_query`** + **`web_search`** in ONE turn — varied queries covering all 3 task categories + tools section.
3. **`verify_url`** in ONE turn on every candidate URL. Drop dead URLs.
4. **(optional)** `read_skill_reference("execute", "REFERENCES.md")` for target/OSS/CTF methodology.
5. **Final turn** — emit Plan JSON with 3 tasks + tools_section.

## Hours allocation

Total target_hours splits across the 3 tasks. The user picks ONE target from each task's resource list and spends the allocated time hunting that target. So:
- Task 1 hours = time to hunt ONE chosen program (1-2h typical)
- Task 2 hours = time to audit ONE chosen OSS project (1-2h typical)
- Task 3 hours = time to attempt ONE chosen CTF/event task (0.5-1h typical for the recon/registration step, the actual event happens later)

Make the description explicit: "Pick ONE target from the resources below and spend [N]h hunting it. Save the others for future sessions."

## Filter rules — what to EXCLUDE

- Generic homepages (hackerone.com root, bugcrowd.com root, owasp.org, github.com root) — link to a SPECIFIC program / OSS project / event page only.
- Bug bounty platforms as a category (the platform isn't an opportunity, programs ARE).
- Lab platforms (already covered in practice phase).
- Theory reading or writeups (wrong phase).
- Niche/low-impact OSS projects (drop if popularity floor not met).
- Past CTFs that already ended (must be live or upcoming).
- Programs / OSS / events the user has already targeted (check via `search_consumed_resources`).
- **Blog posts, advisories, writeups** — research phase.
- **Tool-building tasks** — research phase. The Tools Section lists tools to USE, not to build.

## When to call read_skill_reference
- For target identification methodology, recon angles per bug class, OSS attack-surface evaluation → `read_skill_reference("execute", "REFERENCES.md")`.
- For CTF/event discovery methodology → load REFERENCES.md.

## Completion signals (when to suggest research phase)
- User has submitted ≥3 reports / CVE-track advisories for this bug class
- User has confirmed findings across BOTH bug bounty programs AND OSS projects
- User is starting to identify novel patterns vs known ones

When you see these signals, mention in the rationale that the user is execute-mature and the research phase (gap analysis, bypass hunting, draft generation — including blog posts, conference talks, AND tool building / OSS contribution) is now worth considering.

## Output format
Strict JSON. EXACTLY 3 tasks in the order specified above. Plus the `tools_section` field on the Plan.

```json
{
  "bug_class": "...",
  "phase": "execute",
  "date": "...",
  "target_hours": 3.0,
  "rationale": "...",
  "tasks": [
    {
      "title": "Hunt postMessage on live bug bounty programs — pick ONE target",
      "task_type": "bug_bounty",
      "priority": "high",
      "estimated_hours": 1.5,
      "primary_resource_url": "<first program URL>",
      "primary_resource_name": "<first program name>",
      "resources": [
        {"url": "...", "name": "...", "note": "scope + payout signal"},
        ...
      ],
      "description": "Pick ONE program from the resources. Spend 1.5h on recon + hunt. Deliverable: submitted report OR recon note.",
      "why": "..."
    },
    {
      "title": "Hunt postMessage on popular OSS projects — pick ONE target",
      "task_type": "bug_bounty",
      "primary_resource_url": "...",
      "resources": [
        {"url": "...", "name": "...", "note": "260k weekly npm downloads"},
        ...
      ],
      ...
    },
    {
      "title": "Register / engage with active postMessage-relevant CTFs / hackathons",
      "task_type": "ctf",
      "resources": [
        {"url": "...", "name": "...", "note": "Event date: 2026-07-15, registration open"},
        ...
      ],
      ...
    }
  ],
  "tools_section": [
    {
      "url": "https://github.com/thisis0xczar/FrogPost",
      "name": "FrogPost — Chrome extension for postMessage security testing",
      "note": "Live runtime interception, origin-validation analysis"
    },
    ...
  ]
}
```
