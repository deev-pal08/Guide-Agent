---
name: practice-references
description: Methodology for the practice phase — lab batching strategy, when to bundle vs separate, difficulty ramps within a single session, cross-platform exercise selection.
---

# Practice Phase — Methodology Reference

Load when you need help structuring a batched session, picking between platforms, shaping a difficulty ramp, OR distinguishing real practice resources from writeups that leaked into your candidate list.

## Writeup-vs-challenge URL pattern heuristics (READ THIS FIRST)

The single most common mistake in practice planning is treating CTF writeups, exploit gists, and methodology blog posts as practice resources. They are not. The user reads them in the examples or learn phase. In the practice phase the user PERFORMS, they don't READ.

### URL patterns that signal PRACTICE (allow):

| Pattern | Why it's practice |
|---|---|
| `portswigger.net/web-security/.../lab-*` | Lab page with "Access the lab" button |
| `pentesterlab.com/exercises/*` (NOT `/blog/*`) | Exercise page with environment |
| `tryhackme.com/r/room/*` | Room page with deploy button |
| `hackthebox.com/.../machines/*` or `/hacker/hacking-labs` | Machine page |
| `academy.hackthebox.com/module/*` | Module with exercises |
| `ctf.hackthebox.com/event/*` (challenge subpage) | Replayable challenge |
| `overthewire.org/wargames/*/level*` | Level page (SSH info to attempt) |
| `underthewire.tech/wargames/*` | Same |
| `picoctf.org/practice/challenge/*` | Practice gym challenge |
| `cryptohack.org/challenges/*` | Challenge page |
| `ropemporium.com/challenge/*` | Challenge page |
| `pwn.college/dojos/*` | Dojo with hands-on modules |
| `gandalf.lakera.ai`, `promptairlines.com`, `doublespeak.chat`, `eksclustergames.com`, etc. | Interactive challenge UIs |
| `github.com/<author>/<repo>` where the README says "deliberately vulnerable" or "vulnerable lab" | Cloneable vulnerable codebase (DVWA, OWASP Juice Shop, *Goat, postMessageLab, etc.) |

### URL patterns that signal WRITEUP / WRONG PHASE (drop):

| Pattern | Why it's NOT practice |
|---|---|
| `*.medium.com/*`, `medium.com/@*/*` | Almost always a writeup or tutorial |
| `*intigriti.com/researchers/blog/*` | Blog posts — including past CTF challenge writeups |
| `pentesterlab.com/blog/*` | Blog (PentesterLab's challenge pages are at `/exercises/*`) |
| `jub0bs.com/posts/*`, `embracethered.com/blog/*`, `blog.orange.tw/*` | Researcher blog posts (always examples-phase material) |
| `ctftime.org/writeup/*` | Explicit writeup pages |
| `github.com/.../writeups/*`, `github.com/.../solutions/*`, `github.com/.../exploit/*`, `github.com/.../exploit.py` | Solution / writeup artifacts |
| `hackerone.com/reports/*` | Disclosed report (examples phase) |
| `*.gitbook.io/*` covering exploitation techniques | Methodology / cheatsheet (learn phase) |
| `book.*.com/*` covering exploitation | Reference book (learn phase) |
| `*-cheatsheet*`, `*cheat-sheet*` | Cheat sheet (learn phase) |
| `youtube.com/watch?v=*` | Video — almost always a walkthrough/talk (examples or learn phase) |
| Any URL whose page title contains "writeup", "solution", "how I solved", "explained", "walkthrough", "tutorial" | Read-not-do content |

### When in doubt — the litmus test
*"If the user lands on this URL, will they spend their time DOING (typing payloads, running tools, submitting flags, writing exploits) or READING (consuming someone's explanation)?"*

If you cannot confidently say DOING, drop it from practice. The cost of dropping a real practice resource is small (you find another); the cost of including a writeup is large (it ruins the phase by giving the user a crutch).

### Special case: lab + writeup pairs
A common temptation is to assign a lab AND its writeup "in case the user gets stuck." DON'T. The practice phase exists specifically so the user struggles without the solution visible. If they truly cannot solve a lab, they go back to learn/examples — not to a writeup of the lab they're attempting.

## When to bundle vs separate
**Bundle** (one task = many labs):
- Labs from the same platform on the same bug class (always bundle)
- Labs that share a primitive but vary the obstacle (e.g., all SQLi labs that vary the filter)
- Labs that form a natural difficulty ramp (apprentice → practitioner → expert in one bug class)
- Total session ≤5h

**Separate** (one task per lab):
- A single capstone challenge that's expected to take >2h on its own (e.g., a hard HackTheBox box)
- A CTF that's actively running and bound to specific dates
- A code review of a real production-grade codebase (≥4h on its own)

## Platform strengths per bug class
**PortSwigger Web Security Academy:** the default for web bug classes. Labs are short, focused, and have explicit pedagogical ramps. Use as the primary practice source for SSRF, SQLi, XSS, IDOR, OAuth, CORS, JWT, prototype pollution, HTTP request smuggling, web cache deception, server-side template injection, postMessage / DOM-based vulnerabilities. They have the best taxonomy of "lab per failure mode."

**PentesterLab:** stronger for harder web challenges, code review exercises, and language-specific issues (Rails, Java, Node serialization). Lower volume than PortSwigger but each exercise is more substantial. NOTE: their challenge pages live at `pentesterlab.com/exercises/*`, NOT `pentesterlab.com/blog/*` (that's their writeup blog — examples phase).

**HackTheBox:** stronger for integrated/chained challenges. Use for full-machine practice where the bug class is one step in a chain. Less useful for single-bug-class drilling.

**TryHackMe:** stronger for beginners and for non-web bug classes. Less density per topic than PortSwigger for web.

**picoCTF / CryptoHack / OverTheWire:** stronger for crypto, binary exploitation, reverse engineering bug classes. Use for non-web tracks.

**OWASP WebGoat:** dated but covers some classic bug classes well (XXE, mass assignment, command injection variations).

**VulnHub / Root-Me:** wildcard sources — search them when the well-known platforms don't have coverage for a niche bug class.

## Difficulty ramp shape
For a 4h batched session on bug class X:

1. **Warm-up (30 min, 5-8 labs)** — apprentice-level versions where the primitive is in the open. Goal: re-prime pattern recognition.
2. **Main work (2-2.5h, 6-12 labs)** — practitioner-level. Filters, partial validation, encoding tricks. Goal: build the muscle for real-world bypass patterns.
3. **Capstone (1h, 1-3 labs)** — expert/hard. Often require chaining or a non-obvious twist. Goal: prove the muscle memory survives non-trivial obstacles.

If the user's recent feedback shows they breeze through practitioner-level, increase the capstone share. If they're getting stuck at practitioner-level, increase the main-work share and drop the capstone for now.

## "Sticky lab" tracking
The user reports labs where they needed >15 minutes or a hint. These are the user's actual weak points within the bug class — not the bug class as a whole, but a specific failure mode.

When you see sticky-lab feedback, the next plan should explicitly target that failure mode:
- More labs in that specific pattern
- An examples-phase reread of writeups exhibiting that pattern (cross-phase nudge in the rationale)
- A theory-phase pointer back to learn material if the sticky lab reveals a conceptual gap

## Code review exercises
For a code-review-flavored practice task, point to:
- DVWA / WebGoat / PicoGym source
- A historic CVE's repo at the pre-fix commit (provides ground truth)
- A purpose-built audit lab repo from a known researcher

A good code-review task asks: "find every instance of bug class X in this repo, write a one-line PoC per instance, classify by failure mode." Time-box and require the deliverable.

## Cross-platform sequencing
For mastery, the user should hit ≥2 platforms for the bug class:
- Platform A for breadth (PortSwigger, many labs per failure mode)
- Platform B for depth (HackTheBox machine that integrates the bug class into a kill chain)

Sequence Platform A first (build pattern recognition), then Platform B (apply under real conditions). Mention this sequencing explicitly when generating the second-week plan.

