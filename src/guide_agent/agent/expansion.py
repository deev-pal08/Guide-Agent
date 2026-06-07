"""Bug-class term expansion — Lever 3 (LLM-generated synonym set).

For technique-based bug classes ("postmessage", "request smuggling",
"race condition") the literal class name often doesn't appear in
hardcoded resource titles. Search systems with full-text body search
(hacktivity, ctfsearch, web_search) need a wider net to find these.

Workflow:
  1. CLI calls `ensure_expansion(bug_class)` before fan-out.
  2. If the DB has a cached expansion → return it.
  3. Else call Haiku once (~$0.0003), cache, return.
  4. Fan-out passes the '|'-joined synonyms as `bug_class` to every source.

Manual override: `guide expansions <class>` shows/edits the cache.
"""

from __future__ import annotations

import logging

from guide_agent.agent.base import BaseBrain
from guide_agent.config import AppConfig
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a security taxonomy expert. Given a bug class name, \
produce a list of 6-10 search terms (synonyms, related techniques, technical \
keywords) that someone hunting for writeups about that bug class would search \
for across the open web, GitHub, HackerOne, and security blogs.

Rules:
- ALWAYS include the original bug class name as the first item.
- Use lowercase, ASCII, no quotes.
- Include common abbreviations AND full names \
(e.g. 'xss' + 'cross-site scripting').
- Include common technique vocabulary (e.g. for 'postmessage': \
'window.postmessage', 'cross-window communication').
- Include closely-adjacent attack names (e.g. for 'request smuggling': \
'http desync', 'CL.TE', 'TE.CL').
- DO NOT include generic terms like 'vulnerability', 'exploit', 'bug bounty'.
- DO NOT include unrelated bug classes (no 'sql injection' synonyms \
when the class is 'xss').

Output ONLY a JSON array of strings. No prose, no markdown, no key wrapping.
Example for 'xss':
["xss", "cross-site scripting", "dom xss", "stored xss", "reflected xss", \
"mxss", "client-side injection"]
"""


class ExpansionBrain(BaseBrain):
    """Haiku-cheap brain that turns one bug class into a synonym list."""

    brain_name = "expansion"

    def expand(self, bug_class: str) -> list[str]:
        """Single LLM call → list of synonym terms. ~$0.0003 per call."""
        bc = bug_class.strip().lower()
        if not bc:
            return []

        user_msg = f"Bug class: {bc}\n\nReturn the JSON array now."
        raw = self._single_turn(
            model=self.config.llm.conversation_model,
            system=SYSTEM_PROMPT,
            user_message=user_msg,
            max_tokens=512,
        )
        data = self._parse_json_response(raw)
        if not isinstance(data, list):
            logger.warning(
                "Expansion brain returned non-list for %s: %r", bc, data,
            )
            return [bc]

        terms: list[str] = []
        for item in data:
            if isinstance(item, str):
                stripped = item.strip().lower()
                if stripped and stripped not in terms:
                    terms.append(stripped)

        if bc not in terms:
            terms.insert(0, bc)
        return terms


def ensure_expansion(
    config: AppConfig,
    state: StateStore,
    skill_loader: SkillLoader,  # noqa: ARG001 — kept for symmetry with other brains
    bug_class: str,
    force: bool = False,
) -> list[str]:
    """Return the expansion for this bug class, generating + caching if missing.

    Pass `force=True` to regenerate even when a cached copy exists.
    """
    bc = bug_class.strip().lower()
    if not bc:
        return []

    if not force:
        cached = state.get_expansion(bc)
        if cached:
            return cached

    brain = ExpansionBrain(config, state)
    terms = brain.expand(bc)
    if not terms:
        terms = [bc]
    state.set_expansion(bc, terms)
    return terms


def build_search_query(terms: list[str]) -> str:
    """Join terms with '|' for our source-tools' OR-substring matcher."""
    seen: set[str] = set()
    ordered: list[str] = []
    for t in terms:
        t_norm = (t or "").strip().lower()
        if t_norm and t_norm not in seen:
            seen.add(t_norm)
            ordered.append(t_norm)
    return "|".join(ordered)
