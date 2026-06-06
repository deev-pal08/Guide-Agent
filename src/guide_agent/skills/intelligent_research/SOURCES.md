---
name: intelligent-research-sources
description: Source-quality heuristics for intelligent research — how to rank sources within each category, deduplication rules across hardcoded/newsletter/web pools, freshness vs depth tradeoffs.
---

# Intelligent Research — Source Quality Reference

## Source-quality ranking — universal (high → low)

1. **Primary specifications** — RFC, W3C, HTML Living Standard, ECMAScript spec, language references
2. **Authoritative curated knowledge bases** — HackTricks (security framing), PortSwigger Web Security Academy theory pages, OWASP Cheat Sheet Series, MDN (for web specs)
3. **Peer-reviewed academic papers** — arxiv (post-submission to venue), USENIX, IEEE S&P, CCS, NDSS proceedings
4. **Conference talk material** — DEFCON, BlackHat, BSides, OWASP Global AppSec slide decks + recorded talks
5. **Recognized researcher blogs** — researchers who are the named experts on the bug class
6. **Disclosed bug bounty reports** — HackerOne disclosed (high signal when bounty paid), Bugcrowd disclosures, Intigriti hall of fame
7. **CVE descriptions with linked PoCs** — when the PoC is reproducible
8. **Reputable security publications** — PortSwigger blog, embracethered.com, frans rosen's blog, etc.
9. **Vendor security advisories** — Apple, Microsoft, Google, AWS security bulletins
10. **Newsletter aggregators** — useful as discovery sources but always go to the original cited work

## Sources to filter OUT

- AI-generated SEO blog farms (often have shallow / inaccurate content)
- Listicles ("Top 10 bug class X issues") with no specific PoCs
- Vendor marketing posts disguised as research (look for "buy our product" sections)
- Tutorials from platforms with no editorial signal (random Medium posts that aren't from recognized researchers, low-followers Substacks)
- Stack Overflow answers (useful only for spec disambiguation, never as primary source for an attack class)

## Freshness vs depth tradeoffs

**Prefer freshness when:**
- The phase is examples or execute (real-world patterns evolve fast)
- The bug class is in an actively evolving area (AI security, new web specs, recent CVE patterns)
- The user has already consumed the older landmark resources

**Prefer depth when:**
- The phase is learn (foundational theory rarely needs to be the newest)
- The source is the original landmark paper / spec — those don't age
- The bug class is mature and well-understood (XSS fundamentals, basic SQLi)

When in doubt, prefer ORIGINAL sources over RECENT SUMMARIES. The first paper to describe a technique is usually higher signal than the 50th summary blog post.

## Deduplication across pools — practical patterns

- Newsletter article cites a HackerOne report → keep the HackerOne report URL, drop the newsletter summary (unless the newsletter adds new analysis)
- Two blog posts cover the same CVE → keep the post from the original reporter, drop the summaries
- A vendor advisory + an independent writeup of the same bug → keep both (different perspectives)
- HackTricks page + an MDN page on the same API → keep both (different lenses)

## Source-quality heuristics for unknown sources

When you encounter an unfamiliar source via web_search, check:

- **Domain age and reputation** — is the site a recognized security domain or unknown?
- **Author attribution** — is the author named, and does that name appear in other reputable work?
- **Cross-references** — does the post link to primary sources, or does it just claim things without citations?
- **PoC presence** — does the post include reproducible PoC content?
- **Cited by others** — does another reputable source link to or cite this one?

If 3+ of these signals are missing, downrank or drop the source.

## Per-bug-class source canon (when known)

For some well-studied bug classes, recognized "canonical" sources exist:

- **SSRF:** PortSwigger Academy, OWASP SSRF cheat sheet, Orange Tsai's "A New Era of SSRF" talk
- **HTTP request smuggling:** PortSwigger Academy, James Kettle's research
- **Web cache deception:** Omer Gil's research, OWASP cheat sheet
- **OAuth issues:** Dr. Daniel Fett's papers, Sam Curry's writeups
- **Prototype pollution:** Olivier Arteau's research, Snyk's blog
- **postMessage:** Frans Rosén's work, embracethered.com series
- **SAML vulnerabilities:** Duo Labs research, OWASP SAML cheat sheet

Use these as starting anchors — but always fan out to recent material too.

When the user is drilling a bug class with a recognized canonical source, prioritize loading that source's recent material first.
