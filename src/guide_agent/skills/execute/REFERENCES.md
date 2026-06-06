---
name: execute-references
description: Methodology for the execute phase — target identification, OSS attack-surface evaluation, CTF/hackathon discovery, tools section curation. Bug bounty programs + OSS CVE hunting + active competitions only — no building, no writing.
---

# Execute Phase — Methodology Reference

Load when you need help picking targets, scoping recon, evaluating OSS attack surface, finding active CTFs/hackathons, or curating the Tools Section.

## Target identification — three lenses (bug bounty programs)

**Lens 1: Bug-class-specific signals in scope.** Some programs explicitly call out which bug classes are most rewarded. Read the program's scope page carefully. Bias toward programs that:
- Mention the bug class explicitly in their interesting-finds list
- Have past hacktivity disclosures in this bug class (signals they pay for it)
- Have a wide scope (more attack surface)
- Don't blanket-exclude common variants of the bug class

**Lens 2: Asset-fit.** Some bug classes only show up on specific tech stacks:
- postMessage / DOM-based bugs → web apps with rich client-side JS, iframes, embedded integrations, OAuth flows
- Prototype pollution → Node.js apps, npm-heavy stacks
- SSRF → apps that fetch user-supplied URLs (image proxies, webhook integrations, OAuth callbacks, URL previews)
- Cache deception → CDN-fronted apps with path-based caching
- HTTP desync → apps behind multiple proxy hops (CDN + LB + origin)
- XSS → any rich frontend, especially admin panels and customer-facing forms

Pick targets whose stack matches the bug class's surface.

**Lens 3: Bug-class-friendly maturity gap.** Mature programs have had countless hunters look at them — easy bugs are gone. Look for:
- Recently-launched programs (low hunter density)
- Recently-expanded scope (new attack surface)
- Acquisitions where the parent's bounty program now covers the acquired property
- Specialized programs (specific product, less hunter attention)

## OSS CVE hunting — popular projects only

The point of hunting OSS is to find a CVE / GitHub Security Advisory in a project widely used across industry. A CVE in `lodash` or `express` is a recognizable finding; a CVE in a hobby project with 50 stars is not. Apply these filters before recommending an OSS target.

### Popularity floor (enforce strictly)
A candidate must meet AT LEAST ONE of:
- **10,000+ GitHub stars** OR
- **Top 1% download count** on its package ecosystem (npm, PyPI, Maven Central, Crates.io, RubyGems, Composer, Go modules) OR
- **Used by a recognizable company** (look at the GitHub "used by" badge, or grep for the package in major-company package.json files on GitHub) OR
- **>1k stars + active maintenance** (last commit within 6 months) if the package is in a critical security position

If a candidate doesn't meet ONE of these, drop it.

**Cite the popularity signal in the `note` field of each OSS resource entry** — e.g., `"260k weekly npm downloads"`, `"32k stars, used by Vercel/Next.js"`. Don't just say "popular library" — name the metric.

### OSS attack-surface evaluation per bug class
- **postMessage:** browser-bundled libraries (UMD builds) with iframe embedding (analytics SDKs, payment widgets, chat widgets, OAuth helpers). Look for `addEventListener('message')` in the dist/ files.
- **Prototype pollution:** any npm package with deep-merge / extend / set-by-path functions (lodash.merge, lodash.set, deepmerge, etc., and their wrappers).
- **SSRF:** any package that fetches URLs (axios-style wrappers, image-fetchers, RSS-readers, webhook-relayers, link-preview-generators).
- **XSS in libraries:** any UI library that takes untrusted strings and produces HTML (markdown renderers, sanitizers, template engines, rich-text components).
- **Deserialization:** any package that parses/loads structured data via reflection (YAML loaders, JSON+pickle layers, ORM hydrators).
- **Command injection:** any wrapper around shell tools (ffmpeg wrappers, imagemagick wrappers, git wrappers, package-manager wrappers).

### How to find candidate OSS targets quickly
- Search GitHub Advanced Search: `language:javascript stars:>10000 "addEventListener('message')"` (tune per bug class)
- Search npm with the bug class signature: `npmjs.com/search?q=oauth iframe` for postMessage-relevant packages
- Mine recent CVEs in the bug class — every CVE in package X is a signal that PACKAGES SIMILAR to X are also worth checking
- Cross-reference with the reddelexc HackerOne reports archive — if Shopify had a postMessage bug, similar SaaS platforms running similar embedding patterns are candidates

### OSS disclosure path
- Most popular OSS projects have a `SECURITY.md` describing how to report. Use that path.
- For npm-distributed packages, you can also report via GitHub's private vulnerability reporting (if the repo has it enabled).
- For CVE assignment: maintainers usually request the CVE via MITRE / GHSA; you submit through them. You don't need to file directly.

## CTF / hackathon / competition discovery

Bias HEAVILY toward time-sensitive events the user can actually act on:

### What qualifies for Task 3
- **Named events with a public event page + date** (CTFtime listing, official conference CTF page, hackathon registration page)
- **Deadline or event date within the next 30-60 days** (sweet spot — close enough to act, far enough to register)
- **Open to individual participants** — drop invite-only / corporate-only events
- **Bug class plausibly in scope** — web CTFs for web bugs, DeFi CTFs for smart contract bugs, AI security CTFs for prompt injection, etc.

### Sources to mine for events
- CTFtime upcoming page (`ctftime.org/event/list/upcoming`)
- HackTheBox CTF event pages (hardcoded — live + upcoming)
- Pwn2Own schedule pages (Trend Micro ZDI)
- Major conference CTF announcements: DEF CON CTF qualifiers, BSides locations, Black Hat USA training-week CTFs, AppSec Global hackathons
- Bug-class-specific competitions: AI red-teaming (Lakera, Wiz, OWASP GenAI), web competitions (PortSwigger XSS challenges), smart contract (Code4rena, Sherlock)
- Open hackathon platforms (Devpost, MLH) — only if a bug-class-relevant theme

### What to put in Task 3 resource notes
For each event, the `note` field should include: event date, registration deadline, bug-class relevance.
Example: `"Event: 2026-08-12, registration open until 2026-08-05, web exploitation track confirmed"`.

### When no good events exist
If the bug class has no relevant active CTFs in the next 60 days, return `resources: []` for Task 3 and explain in the rationale. Don't pad with stale events.

## Tools Section curation

The Tools Section lists openly-available tools the user can USE for hunting this bug class. Not tools to build (that's research phase) — tools to download and run TODAY.

### What counts as a tool for the section
- **Browser extensions:** Burp Suite extensions (DOM Invader, ParamMiner, etc.), Chrome extensions (FrogPost, Trickest)
- **CLI scanners / fuzzers:** standalone tools that target the bug class (e.g., `paramspider` for IDOR, `ssrfmap` for SSRF, `XSStrike` for XSS)
- **Burp extensions / plugins:** anything in the BApp Store relevant to the bug class
- **Browser-native devtools:** specific Chrome DevTools panels, ApplicationData inspection tools, etc.
- **Curated tool lists:** `awesome-<bug-class>` GitHub repos that aggregate tools (one entry per major awesome list, not a flood)

### What does NOT belong in tools section
- Bug bounty platforms (those are targets in Task 1)
- Lab platforms (practice phase)
- Cheat sheets / methodology pages (learn phase)
- Writeups / reports (examples phase)
- Tools that don't target this bug class

### Tool entry shape
Same as Resource: `{url, name, note}`. The `note` should describe what the tool does in one line + any limitations.
Example: `"FrogPost — Chrome extension. Live postMessage interception + origin-validation analysis. Manifest V3, actively maintained."`

### How many tools per run
5-10 tools per execute run. Quality over quantity — better 5 actively-maintained tools than 15 with 3 abandoned ones.

If the bug class has fewer than 5 quality tools, return what's available (and mention in the rationale that the tooling landscape is thin — a potential research-phase opportunity).

## Scope analysis checklist (bug bounty programs only)
Before recommending a target, mentally verify:
- [ ] Program is currently active (not paused, not deprecated)
- [ ] Scope clearly includes the asset class you'd hunt on
- [ ] The bug class is NOT in the out-of-scope list
- [ ] Disclosure policy lets the user publish findings (so they can be referenced)
- [ ] Triage timeline is reasonable (some programs have 6+ month backlogs)

If any of these fail, drop the target.

## Negative recommendations — programs to AVOID for first runs
- Programs known for aggressive duplicate-marking
- Programs with public bad-reviews from hunters (search r/bugbounty)
- Programs where most reports go to NA/Informative regardless of severity
- Programs with sub-300 USD typical payouts on the bug class

For OSS, AVOID:
- Repos that haven't merged a security fix in over a year (likely unmaintained)
- Repos with a track record of disputing CVEs (some maintainers reject security reports for ideological reasons)
- Frameworks with their own security team (e.g. Node.js core itself, Django, Rails) where the bar is extraordinarily high

For CTFs, AVOID:
- Past events with no replayable practice mode
- Invite-only / corporate-only events the user can't join
- Events with no clear bug-class connection

## Recon vs hunt time allocation
For a 1-2h execute task targeting one program or OSS project (after the user picks ONE from the resources list):
- 15-30 min recon (map the surface for the bug class)
- 60-90 min hunt (test specific candidates)
- 10-15 min finding-record (document the recon for the next attempt)

## NOT in execute phase
- **Blog posts, advisories, writeups, conference talks** — research phase's `draft_generation` sub-mode
- **Tool building / OSS contribution** — research phase
- **Reading anything new** — wrong phase entirely

If the user asks for one of these via free-text, redirect them to the research phase in the proposal step.

