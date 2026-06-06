---
name: practice
description: Hands-on practice for a single bug class — labs, CTFs, code review exercises. The user PERFORMS the exploit themselves; they do NOT read about how someone else solved it. Batch ALL related exercises into ONE comprehensive task per topic, not one lab per task. NO theory reading — theory was already drained in the learn phase. NO writeups — those are examples phase.
---

# Practice Phase

## Mission
Turn theoretical knowledge (learn phase) + real-world pattern recognition (examples phase) into reliable muscle memory. After this phase, the user should be able to find and exploit the bug class on a new target without referring back to notes. This is where the brain shifts from "I understand this" to "my fingers know what to type."

## Inputs
Same as learn/examples — bug class, target hours, consumed resources, mastered classes, recent feedback.

## WHAT COUNTS AS PRACTICE (HARD RULES)

A practice resource MUST be an environment where THE USER PERFORMS THE EXPLOIT — not reads about someone else's solution. Reading about an exploit is examples phase. Reading methodology is learn phase. Performing the exploit yourself is practice.

### ALLOWED (real practice resources):
- **Replayable lab pages** with a "submit your solution" UX:
  e.g. `portswigger.net/web-security/.../lab-*`, `pentesterlab.com/exercises/*`, `tryhackme.com/r/room/*`, `hackthebox.com/.../machines/*`
- **Active scoreboarded CTF challenges** the user can start NOW:
  picoCTF practice gym, HTB CTF past events that are still replayable on the platform, Root-Me challenge pages, OverTheWire/Underthewire level pages
- **Downloadable / cloneable vulnerable labs**:
  e.g. GitHub repos that ARE the deliberately-vulnerable codebase (OWASP Juice Shop, DVWA, t4kemyh4nd/postMessageLab, Damn Vulnerable * apps, *Goat, etc.)
- **Browser-native challenge pages** (Gandalf, Prompt Airlines, Wiz CTFs, XSS Game) — the user interacts with the live UI
- **Lab platform challenge URLs** that the user enters and performs from scratch

### FORBIDDEN in practice phase:
- Blog posts and writeups (those are examples phase)
- Cheat sheets, methodology guides, exploit references (those are learn phase)
- A CTF *writeup* explaining how someone solved a past CTF — that's an examples resource
- A standalone exploit payload file from a past CTF (e.g. github.com/.../exploit) — that's an examples resource (a solution artifact)
- Conference talks, video lectures, podcasts about exploitation
- Anything where the primary content is "here's how I/you exploit X" rather than "here's the challenge for you to attempt"

### Litmus test for any candidate URL
Ask: *"If the user lands on this URL, will they spend their time DOING (typing payloads, running tools, submitting flags, writing exploits) or READING (consuming someone's explanation)?"*
- DOING → practice
- READING → wrong phase, drop it

## Sources you mine

**Hardcoded pool (per config):** PortSwigger Labs, PentesterLab tracks, HackTheBox hacking-labs, HackTheBox Academy catalogue, HackTheBox past CTFs (the replayable challenges, NOT the writeups), TryHackMe challenges + AI upskilling, pwn.college, Cryptopals, Hextree, Code Review Lab, plus the AI/Cloud/Mobile/Web3/Network/Crypto/RE/IaC pools.

**Newsletter DB:** mostly irrelevant for practice (newsletter is reading material). Skip.

**Web search:** for specific labs/challenges not in the hardcoded pool. CAREFUL — bias your queries toward the challenge platforms, NOT toward "writeup" or "solution" content. Sample query patterns:
- `"site:portswigger.net/web-security <bug-class> lab"` — discover specific lab pages
- `"<bug-class> tryhackme room"` — find THM rooms
- `"<bug-class> HackTheBox machine"` — find HTB boxes
- `"<bug-class> vulnerable lab github"` — find downloadable vulnerable apps
- `"<bug-class> CTF challenge playable"` — find live or replayable CTF challenges
- `"site:overthewire.org <bug-class>"` — find wargame levels

NEVER use queries like `"<bug-class> CTF writeup"` or `"<bug-class> exploit explained"` — those return wrong-phase content.

## Tool loop

1. **`search_consumed_resources`** — drop already-done labs.
2. **`web_search`** (3-5 queries in one turn) using ONLY practice-oriented queries (see above).
3. **`verify_url`** in ONE turn — labs frequently get URL changes or get deprecated; verify before assigning.
4. **For each candidate URL: apply the litmus test.** If the page is a writeup / blog / explanation, DROP IT. Find a replacement.
5. **(optional)** `read_skill_reference("practice", "REFERENCES.md")` for batching methodology + writeup-detection patterns.
6. **Final turn** — emit Plan JSON.

## Ambition rule — BATCH ALL RELATED LABS
The defining failure mode in the practice phase is "one lab per task." The user wants to BATCH all related labs into one comprehensive session so they build pattern recognition by repetition.

**Bad task:**
- "Complete PortSwigger lab: Reflected XSS into HTML context with nothing encoded (0.5h)"

**Good task:**
- "Complete ALL 30 PortSwigger Web Security Academy labs in the access control track in one extended session (4-5h). Don't move on until each lab is solved without hints. Note any lab where you needed >15 minutes — those are the patterns you don't yet have muscle memory for. Output: a list of the 'sticky' labs with one sentence on what tripped you up."

A good practice-phase plan usually has 1-2 batched-volume tasks (each ~3-5h) totaling ~target_hours.

## Difficulty ramp
For a single bug class, batch labs into a ramp:
- 5-10 easy labs to warm up pattern recognition (apprentice / easy / introductory)
- 5-10 intermediate labs that introduce filters/partial defenses (practitioner / medium)
- 3-5 hard labs that require chaining or non-obvious bypasses (expert / hard)

This ramp belongs in ONE task description, not three separate tasks.

## Task-type rules
- ALL tasks MUST have `task_type` in `{lab, ctf, code_review}`. No theory reading (already done).
- `lab` = a guided exercise environment with a "submit flag / solve" UX. NOT a blog explaining a lab.
- `ctf` = a challenge in an ACTIVE OR REPLAYABLE CTF the user can solve themselves right now. NOT a writeup of a past CTF challenge.
- `code_review` = a vulnerable open-source repo or deliberately-vulnerable codebase the user audits themselves. NOT a blog post analyzing one.

## NO CRUTCHES IN THE RESOURCES LIST
The user goes into the practice phase to STRUGGLE productively. Do NOT include "cheatsheets to consult when stuck" or "reference docs to fall back on" in the resources list — those are learn-phase material the user has already absorbed. Adding them as crutches defeats the phase. If the user needs them they can search their notes; the agent's job is to ASSIGN, not to hand-hold.

## When to call read_skill_reference
- If you need help judging difficulty ramp slope → `read_skill_reference("practice", "REFERENCES.md")`.
- If you're choosing between two platforms and unsure → load REFERENCES.md.
- If you're unsure whether a candidate URL is real practice vs a writeup → load REFERENCES.md for the URL-pattern heuristics.

## Completion signals (when to suggest advancing to execute)
- Phase progress shows 20+ labs/challenges completed for this bug class
- Recent feedback shows independent solves (no "needed hint" notes)
- Average actual_hours < estimated_hours (user is faster than expected)
- User has solved at least one hard-difficulty challenge solo
- User explicitly states readiness for real targets

## Output format
Strict JSON. 1-3 ambitious batched tasks, each touching multiple labs in one session. Every URL in `resources` MUST pass the litmus test.
