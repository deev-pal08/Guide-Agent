---
name: learn-references
description: Deeper methodology for the learn phase — topic-extraction heuristics, depth-vs-skim detection, source quality ranking, batching strategies, completion signals.
---

# Learn Phase — Methodology Reference

Load this when you need help judging whether a bug class is truly "drained," when batching is non-obvious, or when the user's recent feedback suggests surface-only engagement.

## Topic-extraction heuristic
For any bug class, mentally enumerate the sub-areas BEFORE building tasks:

- **The API/feature itself** — what it does, what the spec says
- **The threat model** — what's a developer trying to prevent
- **Direct attack patterns** — the obvious primitives
- **Validation patterns** — common defensive code patterns
- **Validation bypasses** — common ways the defenses break
- **Variants by context** — same bug class in different stacks/languages
- **Adjacent bug classes** — what often chains with this one
- **Historical evolution** — how the attack class changed over time
- **Spec gaps** — where the spec is ambiguous and implementations diverge

A task that doesn't cover at least 3-4 of these dimensions is incomplete. Either expand the task or assign a follow-up.

## Source-quality ranking (descending)
1. **Original specifications** (RFC, W3C, HTML Living Standard, ECMAScript spec, language references) — the ground truth.
2. **Authoritative knowledge bases** — HackTricks (for security framing), PortSwigger Web Security Academy theory pages, OWASP Cheat Sheets, MDN (for web specs).
3. **Foundational research papers** — taxonomy papers that DEFINE the attack class (not case studies — those are examples phase).
4. **Recognized practitioner blogs** — researchers who are the named experts on the bug class. Quality varies wildly per post; verify cited claims.
5. **Video tutorials from named experts** — LiveOverflow, IppSec (his theory videos, not box walkthroughs), specific university course lectures.

**Avoid:** AI-generated SEO blog spam, content farms ("Top 10 ..." listicles), tutorials from sites with no editorial signal.

## Depth vs skim detection
Signals the user is SKIMMING rather than DRAINING:
- Completion notes are <50 chars or generic ("read it", "done")
- `actual_hours` is consistently <30% of `estimated_hours`
- Recent feedback says "very easy" on substantive material
- User has consumed many resources but the phase progress notes show shallow recall

When you detect skimming, change tactic in the next plan:
1. Assign FEWER but DEEPER tasks (e.g., 1 task at 4h instead of 3 tasks at 1h)
2. Require explicit deliverable in the description (e.g., "produce a written taxonomy" or "compare 3 implementations")
3. Note the skim pattern in your plan rationale so it's visible

## Batching rules
Tasks should batch resources when:
- Multiple resources cover the same sub-area from different angles (always batch)
- Each resource is <30 min individually (always batch)
- Resources should be cross-referenced for completeness (batch with explicit "compare and contrast")

Tasks should NOT batch when:
- A single resource is a 3+ hour course or paper (it stands alone)
- The resources cover fundamentally different sub-areas that can't be cross-referenced productively
- One source is foundational and others build on it (assign foundational first as a prerequisite task, then the dependents)

## Completion signals (when to suggest advancing to examples)
- Phase progress shows 15+ resources consumed in `learn`
- Recent feedback notes show user can articulate techniques without referring back
- User has covered all sub-areas in the topic-extraction heuristic above
- User notes show confidence (e.g., "this was straightforward, ready for examples")

When you see ≥3 of these signals, mention it in your plan rationale: "Based on phase progress and feedback, you're nearing learn-phase completion — once you finish today's task, examples phase will be the natural next step."

## Cross-class compression
If the user has mastered a related bug class, COMPRESS the learn phase to skip the overlapping basics:
- Mastered DOM XSS → in postMessage learn, skip JS sources/sinks, skip event listener basics
- Mastered SSRF → in cache deception learn, skip basic URL parsing primer
- Mastered XXE → in SSRF learn, skip XML parser basics

State the compression in the plan rationale so the user understands why the task is more focused than a generic learn-phase plan would be.
