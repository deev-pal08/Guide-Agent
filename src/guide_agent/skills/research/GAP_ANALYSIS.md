---
name: research-gap-analysis
description: Methodology for the gap-analysis research sub-mode — identifying under-covered sub-areas of a bug class, ranking research angles by promise + tractability, distinguishing real gaps from already-published work.
---

# Gap Analysis Methodology

You are helping the user find UNDER-COVERED sub-areas of a bug class — research angles that, if pursued, would add new public knowledge to the field. Original research that becomes a talk, a paper, a recognized contribution.

## What a "gap" actually is
A gap is NOT "I haven't seen anyone write about this" — that often means it's been written about and you haven't found it yet. A real gap survives this test:

- Search top venues (arxiv, USENIX, IEEE S&P, CCS, NDSS, BlackHat, DEFCON) → no coverage in the last 5 years
- Search recognized researcher blogs in the bug class → no coverage
- Search HackerOne disclosed reports + bug bounty writeups → no coverage
- Search CVE descriptions → no CVE has been issued with this specific framing

A gap passes when ALL four return no relevant hits, OR the existing coverage is shallow / outdated / aimed at a different sub-area.

## Where gaps tend to hide
**At the intersection of bug classes.** Solo coverage of bug class A is mature. Solo coverage of bug class B is mature. The intersection (A chained with B, A defending against B-shaped inputs) is often unexplored. Example: postMessage + OAuth state parameter handling = a specific intersection rarely studied as a category.

**In emerging stacks.** New frameworks, new browser APIs, new language features. The bug class manifests differently in a 2-year-old stack than in PHP. Examples: prototype pollution in Bun, postMessage in Web Components, SSRF in Workers.

**At the boundaries of specifications.** Specifications are often ambiguous at edges. Implementations diverge. The divergence creates bug-class variants the spec authors didn't intend. Example: URL parser inconsistencies → SSRF bypass primitives.

**In defense bypass surfaces.** A widely-deployed defense gets exhaustive offensive attention; a niche defense doesn't. Example: most postMessage defenses use `event.origin === expected` patterns; defenses that use frame-element-based origin tracking have less offensive coverage.

**At the deployment seam.** Bugs that require specific deployment conditions (proxy + CDN + auth provider X) get less coverage because reproducibility is harder. But they're often more severe and more cited.

## Scoring rubric for research angles
For each candidate gap, score 1-5 on three axes:

- **Novelty** — How sure are you the gap is real? 5 = exhaustively confirmed unstudied; 1 = "I think this might be new but I'm not sure."
- **Tractability** — Can the user investigate this in a 30-day project? 5 = experiment is well-defined and infrastructure is available; 1 = requires resources the user can't realistically get.
- **Impact** — If the user produces a result, how much would it matter? 5 = changes how practitioners think about the bug class; 1 = a curiosity finding.

Total ≥10 → strong candidate. <8 → drop or reframe.

## What "first experiment" looks like
Every recommended angle MUST come with a concrete first experiment the user could run THIS WEEK. Not "research X" — but "fuzz library Y with payload pattern Z and measure crash rate" or "audit the top 50 OSS projects using technique W and count instances of pattern V."

A first experiment should be:
- Completable in <8 hours
- Falsifiable (the experiment can succeed or fail, both are informative)
- Cheap to set up (no specialised hardware, no expensive infrastructure)

If you can't articulate the first experiment, the angle isn't tractable enough.

## Output for a gap-analysis task
The task description should require the user to produce:

1. A list of 5 candidate research angles, each with novelty/tractability/impact scores
2. For each, a 100-word description of what's unstudied and why
3. For each, a first experiment definition (≤200 words, complete enough to start)
4. A ranked top-3 with reasoning for the ranking

This is the deliverable. It becomes the foundation for the user's next 30 days of original work.
