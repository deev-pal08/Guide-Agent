---
name: execute
description: Hunt for real findings on real targets. EXACTLY 3 tasks per run — Task 1 live bug-bounty programs paying well, Task 2 popular open-source projects worth a CVE (popularity-first, NOT bug-class-filtered), Task 3 upcoming CTFs / hackathons / competitions. Plus a Tools Section listing openly-available tools for the current bug class. The OSS + CTF picks are AMBIENT (best targets right now), bug class only smart-prioritizes which programs / repos / events to surface first.
---

# Execute Phase

## Mission
The user has drained theory (learn), absorbed real-world patterns (examples), and built muscle memory through hands-on practice. Execute is where they HUNT — on live bug bounty programs, on popular open-source projects, and in active CTFs/competitions.

**Critical mental model:** Bug class is mostly **noise** when discovering execute targets. A bug bounty program either accepts reports or doesn't — there's no "XSS-only program". A popular OSS library is worth auditing regardless of which bug class the user just mastered. CTFs run for everyone. **So Task 2 and Task 3 are AMBIENT** — the same high-quality opportunities surface for any bug class. **Task 1 uses bug class as a SMART SIGNAL** (programs that have paid for similar bugs in the past get prioritized) but doesn't filter out unrelated programs. **Tools Section IS bug-class-specific** because the user's current mastery dictates which tools they need.

## STRICT STRUCTURE — exactly 3 tasks + 1 tools section per run

Every execute plan has EXACTLY THREE tasks, in this order:

### Task 1 — Live Bug Bounty Programs (task_type=bug_bounty)
3-5 distinct LIVE bug-bounty programs the user can hunt on TODAY. Bias toward programs that:
- Pay well (recent $5k+ bounties visible on hacktivity)
- Have broad scope (especially web + API)
- Have recently paid for the user's current bug class (smart-prioritize, don't filter)
- Are not yet in the user's consumed_resources ledger

Each resource = specific program page (not a platform homepage). Example URLs:
- `https://hackerone.com/shopify` (specific program)
- `https://www.bugcrowd.com/programs/<vendor>`
- `https://www.intigriti.com/programs/<vendor>`
- Vendor-direct programs: `https://www.microsoft.com/en-us/msrc/bounty`, `https://www.mozilla.org/en-US/security/bug-bounty/`

Use `prefetched_resource_search` first (the populate pass tagged programs surfaced by web_search). If the user has consumed many, fall back to live web_search with queries like:
- `site:hackerone.com/<random program> bounty`
- `vendor bug bounty paid out` (catches recent disclosed program signals)
- `bug bounty hall of fame 2026`

### Task 2 — Popular OSS Projects to Audit for CVEs (task_type=bug_bounty)
3-5 distinct POPULAR open-source projects the user can audit with realistic CVE potential. **AMBIENT — not bug-class-filtered.** The agent's job is to surface high-impact OSS targets that:
- Have 10,000+ GitHub stars (preferred floor: 5,000+ if stack-specific niche)
- Are actively maintained (last commit within 6 months)
- Are widely deployed (used by major companies, top 1% downloads on their ecosystem)
- Have HUMAN-WRITTEN code with attack surface (not just docs / configs / curated lists)

Use `prefetched_resource_search` with source=`popular_oss` first (the populate pass pulled the top 50-80 OSS targets across major ecosystems via GitHub Search by stars). Then surface 3-5 best fits.

**For each OSS target's `note` field, cite the popularity signal explicitly:**
- "320k stars, primary front-end framework — `react`"
- "180k stars, runs >40% of websites — `wordpress`"
- "62k stars, default Node.js framework — `express`"

Bug class can SMART-PRIORITIZE but not FILTER:
- For XSS / DOM mastery → bias toward frontend libraries (React, Vue, Svelte, Next.js)
- For SSRF / RCE → bias toward backend frameworks (Express, Django, Spring, Laravel)
- For deserialization → Java / Ruby / Python ecosystems
- For prototype pollution → npm packages

If no bias fits, return the highest-stars projects across all languages.

### Task 3 — Upcoming CTFs / Hackathons / Competitions (task_type=ctf)
3-5 distinct LIVE OR UPCOMING events (start date within next 60 days) where the user can compete.

Use `prefetched_resource_search` with source=`ctftime` first (the populate pass pulled all upcoming CTFs from CTFtime API with weight/format/restrictions metadata). Surface 3-5 best fits.

**Selection criteria (AMBIENT — bug class is NOT a filter):**
- CTFtime weight ≥ 25 (notable events) when available
- Format: Jeopardy (individual or small-team friendly)
- Restrictions: Open (skip students-only / corporate-only unless user qualifies)
- Start date next 7-60 days (skip "starts in 6 months" — too speculative)

Note in the `note` field: "Format: Jeopardy, Open, weight=42, starts 2026-07-15".

For non-CTFtime events (hackathons, AI-red-team competitions), supplement with `web_search`:
- `AI red team competition 2026`
- `bug bounty hackathon 2026`
- `BSides CTF 2026 registration`

### Tools Section (NOT a task — separate `tools_section` field on the Plan)
5-10 openly-available tools the user can USE for hunting the **current bug class**. These are tools to download/run, not tools to build.

**Use prefetched_resource_search with source="hunting_tools" first** — the populate pass ran `github_repos_by_stars` with bug-class-tuned hunting queries (`<bug_class> scanner`, `<bug_class> exploitation`, `<bug_class> fuzzer`, `<bug_class> burp extension`, `<bug_class> tool`) and tagged the results. Surface 5-10 best fits with descriptive notes (what makes each useful for THIS bug class).

If the DB is empty or you want fresh tool discovery, fall back to direct calls:
- For postMessage: `github_repos_by_stars(query="postmessage exploitation", min_stars=50)` → FrogPost etc.
- For XSS: `query="xss scanner"`, `query="xss payload"`, etc.
- For JWT: `query="jwt cracker"`, `query="jsonwebtoken security"`

Each tool entry needs: url + name + note (what makes it useful for THIS bug class).

## Source pool
- **prefetched_resource_search** → Task 1 (web_search + hardcoded_hubs), Task 2 (popular_oss), Task 3 (ctftime + web_search), Tools Section (hunting_tools) — all DB-cached from the populate pass
- **hackerone_hacktivity_search** → smart-prioritize Task 1 (programs that recently paid for current bug class)
- **github_repos_by_stars** → live for Tools Section fallback + Task 2 fallback if DB exhausted
- **ctftime_events** → live for Task 3 fallback
- **web_search** → live for Task 1 program scope hunting, hackathons not on CTFtime

## Filter rules — what to EXCLUDE
- Generic homepages (hackerone.com root, bugcrowd.com root, github.com root) — link to specific program / project / event page only.
- Bug bounty platforms as a category (the platform isn't an opportunity, programs ARE).
- Lab platforms (already covered in practice phase).
- Theory reading or writeups (wrong phase).
- Niche / low-impact OSS projects (popularity floor 5k+ stars, prefer 10k+).
- Past CTFs that already ended.
- Programs / OSS / events the user has already targeted (check via `search_consumed_resources` and the consumed_urls exclusion in prefetched_resource_search).
- **Blog posts, advisories, writeups** — research phase.
- **Tool-building tasks** — research phase. The Tools Section lists tools to USE, not to build.

## When to call read_skill_reference
- For program scope evaluation methodology, OSS attack-surface tactics → `read_skill_reference("execute", "REFERENCES.md")`.
- For CTF / event discovery beyond CTFtime → load REFERENCES.md.

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
      "title": "Hunt on live bug bounty programs — pick ONE target",
      "task_type": "bug_bounty",
      "priority": "high",
      "estimated_hours": 1.5,
      "primary_resource_url": "<first program URL>",
      "primary_resource_name": "<first program name>",
      "resources": [
        {"url": "...", "name": "Shopify program", "note": "Paid $3000 for postMessage XSS in Oct 2024, broad in-scope"}
      ],
      "description": "Pick ONE program. Spend 1.5h on recon + hunt. Deliverable: submitted report OR recon note.",
      "why": "..."
    },
    {
      "title": "Audit popular OSS for CVEs — pick ONE target",
      "task_type": "bug_bounty",
      "primary_resource_url": "https://github.com/expressjs/express",
      "resources": [
        {"url": "https://github.com/expressjs/express", "name": "expressjs/express", "note": "67k stars, Node default web framework, JS — fits postMessage / DOM bias"},
        {"url": "https://github.com/vercel/next.js", "name": "vercel/next.js", "note": "133k stars, prod-deployed React framework"}
      ],
      "description": "Pick ONE OSS project. Spend 1h on attack surface mapping + audit. Deliverable: CVE-track advisory or security issue.",
      "why": "..."
    },
    {
      "title": "Register / engage with upcoming CTFs / hackathons",
      "task_type": "ctf",
      "resources": [
        {"url": "https://ctftime.org/event/2913/", "name": "SSMCTF 2026", "note": "Jeopardy, Open, weight=15, starts 2026-06-07"}
      ],
      "description": "Pick ONE event. Register + plan participation. Deliverable: registered + calendar block.",
      "why": "..."
    }
  ],
  "tools_section": [
    {
      "url": "https://github.com/thisis0xczar/FrogPost",
      "name": "FrogPost",
      "note": "Chrome extension — live postMessage interception + origin-validation analysis"
    }
  ]
}
```
