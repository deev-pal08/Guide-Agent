---
name: research-bypass-hunting
description: Methodology for the bypass-hunting research sub-mode — cataloguing known defenses, identifying weaknesses or untested edges, generating candidate bypass primitives to test.
---

# Bypass Hunting Methodology

You are helping the user find weaknesses in DEFENSES against a bug class. Original work in this mode produces publishable bypass primitives, CVE-worthy advisories, and conference-talk material.

## The structure of every defense
Every defense for a bug class can be decomposed into:

- **Trust boundary** — where attacker input becomes "trusted" within the system
- **Validation function** — the code that decides whether input crosses the boundary
- **Threat model** — what threats the defense is designed to stop
- **Implicit assumptions** — what the defense assumes about its environment

Most bypasses live in the gap between the threat model and the implicit assumptions — the defense was correct for the threats the author considered, but wrong about something the author assumed but didn't check.

## Defense-bypass discovery process

**Step 1 — Catalogue defenses comprehensively.**
For the active bug class, list every named defense pattern:
- OWASP cheat-sheet recommendations
- Framework-built-in protections (Angular, React, Spring, Rails, Django)
- Library-provided protections (DOMPurify, JsonSchema, validator.js, etc.)
- Spec-mandated protections (Same-Origin Policy, SameSite cookies, CSP)
- Application-layer custom defenses common in industry

For each, note: WHO advocates for it, WHEN it was introduced, WHAT exact threat it addresses.

**Step 2 — Decompose each defense.**
For each defense, articulate the four parts above (boundary, validation, threat model, implicit assumptions). This is your offensive map.

**Step 3 — Find untested edges.**
For each defense, ask:
- What inputs has the validation function NEVER been tested against?
- What environmental assumptions does the validation rest on, and when do those assumptions fail?
- What versions / configurations of the defense exist, and do bypasses in one apply to others?
- What's the failure mode if the defense errors out (fail-open or fail-closed)?

**Step 4 — Propose bypass primitives.**
For each promising edge, propose a CONCRETE bypass primitive — a specific payload pattern or input shape the user can test.

## Where bypasses commonly hide

**Parser inconsistencies.** The defense parses input one way; the consuming code parses it differently. URL parsers, JSON parsers, MIME parsers, encoding decoders. Test: build inputs that the defense's parser accepts as "safe" but the consumer parses as something different.

**Stale defenses.** The defense was designed for HTTP/1.1 but the app speaks HTTP/2. The defense assumes a single proxy hop but the app has CDN + LB + origin. The defense assumes UTF-8 but a downstream uses UTF-16. Test: replay attacks via the protocol/encoding the defense wasn't designed for.

**Boundary slippage.** The defense protects boundary A but a sink at boundary B receives the same data unprotected. Common in template engines (escaped in one context, unescaped in another).

**Type confusion.** The defense checks the value but not the type. A property assumed to be a string can be an array/object/null and bypass the check.

**Time-of-check / time-of-use.** The defense validates input at time T1, but the input is used at time T2, and something changed between them. Race conditions, async re-entry, stale cache.

**Composability bugs.** Defense A + Defense B were each safe individually; combining them creates a new bypass surface neither author considered.

## Documenting a bypass primitive
A bypass primitive worth pursuing has:

- A specific defense it bypasses (named, versioned)
- A specific payload pattern (not "fuzz it" — an actual payload)
- A specific test environment to verify it (named target type)
- An estimate of impact if confirmed (severity + breadth of affected systems)

Without all four, the primitive isn't actionable.

## Output for a bypass-hunting task
The task description should require the user to produce:

1. A defense catalogue table (defense name, scope, version, known bypasses if any)
2. A decomposition for the top 3 defenses (boundary, validation, threat model, implicit assumptions)
3. For each, ≥2 candidate bypass primitives with payload patterns
4. A short-list of the top 3 primitives to test, with test environment and expected impact

This deliverable feeds directly into the user's next execute-phase session — testing the candidate primitives on real targets.
