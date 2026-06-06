---
name: research
description: Original contribution to the bug class — three sub-modes selected at proposal time. gap_analysis finds what the world hasn't covered. bypass_hunting finds weaknesses in known defenses. draft_generation turns accumulated knowledge into a publishable blog/talk/paper draft. Only run after the user has mastered learn + examples + practice for the bug class.
---

# Research Phase

## Mission
The user has drained theory, internalized real-world patterns, built muscle memory through practice, and executed on real targets. They are now a competent practitioner. This phase pushes them from competent practitioner to ORIGINAL CONTRIBUTOR — someone who adds new knowledge to the field, not just consumes it.

This phase is what separates a senior practitioner from a recognized expert. The world's top researchers in any bug class produce original work — taxonomies that didn't exist, bypasses for defenses everyone assumed were solid, conference talks that change how the bug class is understood.

## Inputs
Same as other phases, plus the user's `consumed_resources` and `recent_completed_tasks` become MORE important here — the research output should be informed by everything the user has already absorbed.

## Three sub-modes
The user picks one sub-mode at proposal time. The user context message will state which sub-mode is active. You MUST call `read_skill_reference("research", "<MODE>.md")` in your first turn to load the methodology for that sub-mode.

- **`gap_analysis`** → load `GAP_ANALYSIS.md`. Find under-covered sub-areas of the bug class and rank them as research angles by promise + tractability.
- **`bypass_hunting`** → load `BYPASS_HUNTING.md`. Catalogue known defenses for the bug class and identify weaknesses or untested edges.
- **`draft_generation`** → load `DRAFT_GENERATION.md`. Turn the user's accumulated knowledge into a structured first draft (blog post, conference talk outline, or research paper outline).

## Sources you mine — DISCOVERY + AUTHORITATIVE

This phase has NO hardcoded source pool — every source comes from live discovery. But the bar is higher than other phases: research output must be grounded in authoritative sources, not blog posts.

**Web search** with academic and authoritative bias:
- arxiv.org for recent research papers in the bug class
- USENIX, IEEE S&P, CCS, NDSS proceedings
- DEFCON / BlackHat slide decks (presentations often contain unpublished research)
- W3C / IETF / vendor security advisories
- Specific researcher blogs known for original contributions in the bug class

**Newsletter DB:** call `newsletter_query` with the bug class + "research", "paper", "novel", "new technique" — surface what's been published recently.

## Tool loop

1. **`read_skill_reference("research", "<SUB-MODE>.md")`** in turn 1 — REQUIRED. Load the methodology.
2. **`search_consumed_resources`** — what's already been absorbed.
3. **`newsletter_query`** + **`web_search`** in ONE turn, with academic/authoritative queries.
4. **`verify_url`** in ONE turn.
5. **(optional)** `read_skill_reference("research", "REFERENCES.md")` only if it exists. The mode-specific reference is the primary methodology.
6. **Final turn** — emit Plan JSON.

## Ambition rule — ORIGINAL CONTRIBUTION
Every task must produce something that adds to the field's knowledge. NOT consumption. NOT practice. CONTRIBUTION.

**Bad task:**
- "Read recent postMessage research papers (2h)"  — this is examples phase, not research

**Good task (gap_analysis):**
- "Identify 5 under-covered sub-areas of postMessage research (3h). Survey the last 24 months of postMessage research (arxiv, Black Hat, DEFCON, conference talks, top hunter blogs). For each, score: (a) how thoroughly the literature covers it, (b) what's still unknown, (c) tractability for a 30-day research project. Output: a ranked list of 5 research angles with 100-word descriptions and a 'first experiment' for each."

**Good task (bypass_hunting):**
- "Catalogue every published postMessage defense pattern and find the gaps (4h). Survey: OWASP cheat sheet defenses, framework-provided protections (Angular, React, etc.), library protections (origin-checking helpers). For each defense, identify: (a) what threat model it covers, (b) what it does NOT cover, (c) one candidate bypass primitive to test. Output: a markdown table of defenses → uncovered threats → bypass primitive to try."

**Good task (draft_generation):**
- "Draft v1 of a blog post titled 'postMessage origin validation: the 5 ways developers get it wrong' (4h). Mine your consumed resources for the 5 most distinctive failure patterns. For each, write: (a) the code anti-pattern, (b) why developers write it this way, (c) the attacker primitive that exploits it, (d) the correct defense. Aim for 1500-2000 words. Deliverable: a markdown draft ready for round 2 editing."

A good research-phase plan usually has 1-2 deep contribution tasks totaling ~target_hours.

## Task-type rules
- All tasks `task_type` in `{research, write, build}`.
- `research` = analytical work that produces new knowledge (gap surveys, bypass enumeration).
- `write` = drafting publishable artifacts (blog posts, advisories, conference talk drafts, papers).
- `build` = building or substantially contributing to open-source security tooling for this bug class. The deliverable is a public GitHub repo, a merged PR upstream, or a published release. Tool-building IS research output because high-quality tooling encodes a deep mental model of the bug class. (Tool USE for hunting is execute phase; tool BUILD is research.)

## Output format
Strict JSON, same as other phases. `research_mode` field MUST be set when phase == research. 1-3 deep tasks.

## When the research output is mature
When the user has:
- Identified a concrete research angle with first-experiment results
- Drafted a publishable artifact
- Tested a candidate bypass primitive in the wild

That's the cue to suggest external steps (submit a talk CFP, publish the blog, file an advisory). Mention this in the plan rationale when appropriate.
