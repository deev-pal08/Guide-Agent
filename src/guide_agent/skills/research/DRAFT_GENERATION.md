---
name: research-draft-generation
description: Methodology for the draft-generation research sub-mode — turning accumulated knowledge (consumed resources + completed practice + bypass discoveries) into a structured first draft of a blog post, conference talk outline, or research paper.
---

# Draft Generation Methodology

You are helping the user produce a publishable first draft — a blog post, conference talk outline, or research paper draft. The output is a finished v1 ready for the user to edit and ship.

## What makes a draft worth shipping
The bar is NOT "rehash of public knowledge." The bar is "something a senior practitioner in the field would learn from." Most published work in security comes from one of these shapes:

- **Failure-mode taxonomy** — "the N ways people get bug class X wrong" with code examples
- **Defense decomposition** — "why defense Y works in theory but fails in practice"
- **New attack primitive** — "this specific bypass / payload / chaining technique was undocumented"
- **Empirical study** — "we audited N projects and found pattern P appears in M% of them"
- **Cross-class chain** — "combining bug class A and bug class B gives you primitive C that neither gives alone"
- **Methodology document** — "how to hunt bug class X efficiently — the recon, the tooling, the heuristics"

Pick ONE shape per draft. Don't mix.

## Shape-specific outlines

### Failure-mode taxonomy
- Title: "Bug class X: N ways developers get it wrong"
- Intro (200 words): what the bug class is, why developers struggle, what this post adds
- For each failure mode (typically 5-7):
  - Anti-pattern code example (50 lines max)
  - Why developers write it this way (cognitive trap)
  - Attacker primitive that exploits it
  - Correct defense pattern
  - 1-2 real-world CVEs / writeups that exhibited this failure mode (link)
- Conclusion (150 words): the meta-pattern across failure modes, a one-line takeaway

Target length: 1800-2500 words.

### Defense decomposition
- Title: "Why [defense] doesn't actually protect you from [bug class]"
- Intro (250 words): defense is widely recommended, here's the threat model it actually covers
- Section 1 — Defense as documented (how it's supposed to work, who advocates for it)
- Section 2 — Defense as implemented (gap between spec and reality)
- Section 3 — Threat model holes (with PoCs)
- Section 4 — Recommended replacement / hardening
- Conclusion: meta-point about defense design

Target length: 2000-3000 words.

### New attack primitive
- Title: catchy, evocative, includes the technique name you're coining
- Intro (200 words): what's new here, what was the prior state of the art
- Background (300 words): minimum reader prerequisites
- The technique (the core): clear, step-by-step, with PoC
- Variants (if any)
- Affected systems (severity + breadth)
- Defenses (what works, what doesn't)
- Disclosure timeline (if applicable)
- Conclusion: implications

Target length: 2500-4000 words.

### Empirical study
- Title: "We audited N [systems] for [bug class] — here's what we found"
- Intro: research question, what was unknown before
- Methodology (replicable): what corpus, what tools, what filters
- Results (with numbers): hit rates, severity distribution, time-to-fix when reported
- Selected case studies (3-5 deep dives)
- Discussion: meta-patterns, defender takeaways
- Limitations

Target length: 3000-5000 words. Plus a public dataset / tool release if possible.

### Cross-class chain
- Title: "Chaining [bug A] with [bug B] for [primitive C]"
- Intro: why this chain matters
- Background on each bug class (assume reader knows both individually)
- The chain (step-by-step with PoC)
- Constraints (what conditions enable the chain)
- Real-world targets where this chain applies
- Defenses

Target length: 1500-2500 words.

### Methodology document
- Title: "Hunting [bug class] — recon, tools, heuristics"
- Intro: who this is for, what experience level
- Recon angles (specific dorks, specific URL patterns to map)
- Tools (named, with how-to-use)
- Heuristics for triaging candidates
- Common false positives
- Notable past finds (link writeups)
- Defenders' perspective

Target length: 2000-3500 words.

## Drafting workflow

**Phase 1 — Outline (30 min).** Pick the shape. Write the section headers. Write 1-2 bullet points under each header about what goes there.

**Phase 2 — Anchor sections (90 min).** Write the 2-3 most concrete sections first — the ones where you already know what to say. These anchor the draft.

**Phase 3 — Connective tissue (60 min).** Write the intro, transitions, and conclusion. These tie the anchors together.

**Phase 4 — Edit pass (30 min).** Read end-to-end. Cut filler. Strengthen weak claims. Add specific numbers / code / CVE links where you waved hands.

Total: ~3.5 hours for a v1 of typical length. Multi-day for a deep empirical study.

## Output for a draft-generation task
The task description should require the user to produce a complete v1 draft of one of the shapes above, with explicit length targets and section requirements. Mention the shape explicitly in the task description so the user doesn't drift into a different format.

The deliverable is markdown text. Publishing is a follow-up — the agent's job is to produce the draft, not host or distribute it.
