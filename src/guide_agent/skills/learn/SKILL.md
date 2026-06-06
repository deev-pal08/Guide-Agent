---
name: learn
description: Drain ALL foundational theory for a single bug class from authoritative sources (HackTricks, PortSwigger Web Security Academy, OWASP guides, cheat sheets, official docs, video tutorials, foundational/taxonomy papers). NO labs, NO CTFs — this phase is theory only. Output is ONE comprehensive task per topic, not many small reading tasks.
---

# Learn Phase

## Mission
Turn the user from someone who has heard of the bug class into someone who has internalized every documented attack methodology, technique, type, variant, and edge case for it. The bar is "world-expert reads this and finds nothing to add" — not "user has seen one tutorial."

This phase is **theory only**. No labs. No CTFs. No real-world reports (those are the examples phase). Drain authoritative sources until the user can explain the bug class from first principles, enumerate its variants, and predict where it will appear in code without ever having seen a real exploit yet.

## Inputs (from the user context block)
- `bug_class_name` and `bug_class_id`
- `target_hours` — soft target, going up to 1.3x is fine to deliver an ambitious task
- `consumed resources` count — what's already been covered, do NOT re-suggest
- `mastered classes` — cross-reference, skip overlap (e.g., already mastered DOM XSS → skip JS sources/sinks fundamentals in postMessage)
- `recent feedback` and `user notes` — adjust depth/difficulty accordingly

## Sources you mine

**Hardcoded pool (per config):** HackTricks, PortSwigger Web Security Academy (theory pages only, NOT labs), OWASP Cheat Sheet Series, OWASP Web Security Testing Guide.

**Newsletter DB:** call `newsletter_query` with the bug class name + 3-4 related keywords. Newsletter content for the learn phase tends to be technical deep-dives and methodology posts, not real-world writeups.

**Web search:** when hardcoded + newsletter don't cover a sub-area. Look for:
- Official RFCs and specifications (e.g., HTML Living Standard for postMessage)
- Vendor docs (MDN, Chromium design docs, language reference docs)
- Foundational/taxonomy research papers (arxiv, USENIX, IEEE) that DEFINE the attack class
- High-quality video lectures (LiveOverflow, IppSec theory videos, university course recordings)
- In-depth methodology blog posts from recognized researchers

**NOT in scope here:** bug bounty writeups (examples phase), labs (practice phase), CFP/program pages (execute phase).

## Tool loop

1. **`search_consumed_resources`** — pass any URLs you already know exist for this bug class to avoid repeats.
2. **`newsletter_query`** + **`web_search`** in ONE turn (batch all queries together). Generate 3-5 varied queries that surface different facets of the bug class — e.g., for postMessage: `["postMessage origin validation theory", "postMessage HTML spec MDN", "OWASP postMessage cheat sheet", "HackTricks postMessage"]`.
3. **`verify_url`** in ONE turn on every candidate URL. Use the returned `page_title` as the resource_name. Drop anything that fails to load or 404s.
4. **(optional)** `read_skill_reference("learn", "REFERENCES.md")` if you need the methodology depth in REFERENCES.md.
5. **Final turn** — emit Plan JSON.

## Ambition rule (HARD)
NEVER assign a single short resource as its own task. Single tutorials, single MDN pages, single cheat sheet sections — all get BATCHED into one comprehensive depth-drilling task.

**Bad task:**
- "Read MDN postMessage page (0.5h)"

**Good task:**
- "Drain ALL foundational postMessage theory in one sitting (3h): MDN postMessage reference, OWASP postMessage cheat sheet, HackTricks postMessage page (including the 'common pitfalls' subsection), and the HTML Living Standard's cross-document messaging spec section. Take structured notes per source on (a) what the API is supposed to do, (b) what the spec leaves implementation-defined, (c) where developers commonly misuse it. Output: a single internal reference doc you can quote later."

A good plan in the learn phase usually has 1-3 substantive tasks totaling ~target_hours. NEVER more than 5.

## Task-type rules
- ALL tasks MUST have `task_type` in `{read, course, research}`. No labs. No CTFs. No bug_bounty.
- `read` = primary, for blog posts, docs, cheat sheets, papers, MDN.
- `course` = structured multi-module learning (PortSwigger Academy theory tracks count).
- `research` = synthesizing reading into a structured note/comparison/taxonomy.

## When to call read_skill_reference
- If you need help deciding source quality, batching strategy, or what "drained" means → `read_skill_reference("learn", "REFERENCES.md")`.
- If the user's recent feedback shows they're skimming surface-only and you want a depth-check methodology → load REFERENCES.md.

## Output format
Strict JSON (see top-level system prompt). No markdown fence. No preamble. `tasks` must have 1-5 entries, each ambitious enough that the user cannot rate it "very easy."
