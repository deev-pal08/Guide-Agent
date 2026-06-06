---
name: examples-references
description: Methodology for the examples phase — report-reading heuristics, pattern-extraction techniques, signal-vs-noise classification, batching strategy, what makes a real-world report high-signal vs low-signal.
---

# Examples Phase — Methodology Reference

Load when you need help judging report quality, picking which reports to batch together, or detecting when the user is checkbox-reading instead of pattern-mining.

## Report quality signals (HIGH-SIGNAL)
- Clear PoC with actual request/response or screenshots
- Explains the attacker's reasoning, not just the steps
- Cites the specific code path that failed
- Discusses what the defender SHOULD have done
- Names the developer mistake explicitly
- Lists the failed mitigation (if any)
- Talks about the discovery process (recon, dorks, hunches)
- Disclosure timeline visible
- Bounty paid (filter to reports with bounty when possible — vendors paying is a vote of severity)

## Report quality signals (LOW-SIGNAL — skip or batch as "for completeness only")
- Title is the bug class name, body is one sentence
- Reproduces a known public PoC verbatim with no new insight
- No code shown — just "I submitted this and got $X"
- "Marked as duplicate" without context
- Vendor responses (NA / Informative) with no insight
- Auto-generated security scanner output

## Sub-area grouping for batched reads
Group reports by failure mode, not by target. Example for postMessage:
- **Group A — Origin check absent:** message handler accepts data from any origin
- **Group B — Origin partial match:** weak prefix/suffix check, regex bypass
- **Group C — Origin null/file://:** sandboxed iframe quirks
- **Group D — Trusted origin but compromised iframe:** redirector/open-redirect on legitimate origin
- **Group E — Message data injection:** trusted origin sends attacker-controlled data, sink in handler
- **Group F — Cross-window exfiltration:** opener/parent leakage

When you batch a task ("read 15 postMessage reports in one sitting"), pick reports across multiple groups so the user sees the variety, not 15 reports all in Group A.

## Pattern-extraction deliverable
The point of an examples-phase task is NOT just to consume URLs — it's to extract patterns. The task description must require a deliverable:

- A taxonomy / failure-mode table
- A "developer mistake → attacker primitive" mapping
- A list of recon signals that hint at this bug class being present
- A list of common false-positives to filter out

Without a deliverable, the user defaults to passive reading and the phase loses its compounding value. Always include one.

## Avoiding writeup overlap
Many high-profile bugs get covered by multiple writeups (the original reporter, blog summaries, podcast recaps, video walkthroughs). Calling these distinct "reports" inflates the count without adding new patterns. When you encounter overlap:

- Pick the original reporter's account (highest fidelity)
- Drop the rest unless they add genuinely new angles

Use `search_consumed_resources` aggressively. If the user has already read the original report, skip the recap blogs.

## Signal that the user is checkbox-reading
- Feedback notes describe what they read but not what they learned
- Pattern: many reports consumed, but recent learn-phase content gets requested ("can you give me more theory")
- Lab attempts in subsequent practice phase show the user can't recognize the attack pattern

When detected, switch tactic in the next plan:
- Fewer reports per task (5-8 instead of 15-20)
- Heavier deliverable requirement (full taxonomy doc, not just bullet points)
- Cross-report compare: "find a pattern that appears in ≥4 of these reports and write a 200-word recon methodology"

## Newsletter vs web search priority
The user's newsletter agent has been curating security writeups for months. Use it FIRST. Web search is for filling gaps.

Newsletter queries return articles already tagged + scored. When you call `newsletter_query`, prefer articles with:
- `priority: CRITICAL` or `IMPORTANT`
- Match score ≥3 (indicates strong keyword overlap)
- Source from recognized researchers' blogs (embracethered, frans rosén, samcurry, hackerone-disclosed, etc.)

Skip articles where the source_name suggests aggregator/newsletter content (those summarize other work — go to the original).
