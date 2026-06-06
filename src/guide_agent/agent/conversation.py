"""Conversation agent — cheap propose-iterate loop before plan generation.

Runs Haiku, NO web_search, NO tools. Reads state, produces a Proposal
with 3-5 options for the user. The CLI loop accepts free-form replies
("more practice", "drop option 2", "harder reports"), feeds them back
to this agent, and regenerates. Tokens are tiny per iteration.

Only once the user explicitly confirms a direction does control hand
off to the planner agent (which is where tools fire and tokens get spent).
"""

from __future__ import annotations

import logging
from typing import Any

from guide_agent.agent.base import BaseBrain
from guide_agent.config import AppConfig
from guide_agent.models import Phase, Proposal, ProposalOption, ResearchMode
from guide_agent.skills.loader import SkillLoader, render_skills_catalogue
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


PHASES_HUMAN = ["learn", "examples", "practice", "execute", "research"]


SYSTEM_PROMPT = """\
You are the Conversation agent for the Guide — a hyper-specific security \
bug-class mastery tool. The user is a senior security engineer (~5 years) \
who wants to master ONE bug class at a time through 4 phases (learn, examples, \
practice, execute) plus a research phase.

## YOUR ONE JOB
Look at the user's state for the active bug class and present 3-5 numbered \
options for what to do next. NEVER fire any tools. NEVER do any research. \
NEVER fabricate URLs or specific resources. You are the "menu" — the planner \
agent fires after the user picks.

## OPTION QUALITY
Each option must:
- Tie to a specific phase (or be "free choice" / "describe what you want")
- Reference the user's actual state (e.g., "you've drained 47 learn resources, \
finish the remaining HackTricks postMessage subpages")
- Be ambitious — never propose trivial single-resource tasks
- Cite past mastery when relevant (e.g., "you mastered DOM XSS — skip JS \
sources/sinks basics")

## MASTERY LOOP (HARD)
The user follows a strict 4-phase loop with mastery gates:
- learn = drain ALL foundational theory (HackTricks, PortSwigger Academy, \
OWASP guides, cheat sheets, foundational papers). No labs.
- examples = read DOZENS of real-world reports (writeups, CVEs, hacktivity, \
case studies). No labs.
- practice = labs/CTFs/code review only, batched into comprehensive sessions
- execute = real targets only (live bug bounty programs, OSS, competitions)
- research = three sub-modes (gap analysis, bypass hunting, draft generation)

Suggest the next phase based on the user's progress, but always include an \
option for "stay in current phase, more depth" because the user has final \
authority over progression.

## INPUT
You receive: bug class name, hierarchy (parent/children/leaf), per-phase \
progress (resources consumed, last run), recent feedback notes, user notes \
(persistent statements from email replies — TREAT AS GROUND TRUTH), mastered \
classes (for cross-class context), available skills catalogue.

If the user has provided iteration feedback ("more practice", "harder", \
"drop option 2"), incorporate it — do NOT ignore them.

## OUTPUT
Return ONLY a JSON object with this exact shape — no markdown, no preamble:
{
  "bug_class": "postmessage",
  "context_summary": "One-paragraph summary of where the user stands.",
  "options": [
    {
      "label": "Short label",
      "phase": "learn|examples|practice|execute|research",
      "description": "What this option will do",
      "rationale": "Why agent suggests this option"
    }
  ],
  "free_text_invitation": "Or describe what you want to do."
}

Set phase to null only for the "free choice" option. Include 3-5 options. \
Always include a free-choice fallback so the user can override.
"""


def _phase_progress_lines(progress: list[dict[str, Any]]) -> list[str]:
    if not progress:
        return ["- (no phase progress yet — this is fresh)"]
    lines = []
    for p in progress:
        last = (p.get("last_run") or "")[:10] or "never"
        lines.append(
            f"- {p['phase']}: {p['resources_consumed']} resources consumed, "
            f"last run {last}"
        )
    return lines


def _build_context(
    bug_class: dict[str, Any],
    progress: list[dict[str, Any]],
    recent_feedback: list[dict[str, Any]],
    user_notes: list[dict[str, Any]],
    mastered: list[dict[str, Any]],
    hierarchy_note: str,
    iteration_history: list[str],
    skills_catalogue: str,
) -> str:
    sections = [f"## ACTIVE BUG CLASS: {bug_class['name']}"]
    sections.append(f"Status: {bug_class['status']}")
    if hierarchy_note:
        sections.append(hierarchy_note)

    sections.append("## PHASE PROGRESS\n" + "\n".join(_phase_progress_lines(progress)))

    if mastered:
        mastered_names = ", ".join(m["name"] for m in mastered)
        sections.append(
            f"## MASTERED BUG CLASSES (cross-reference for context)\n{mastered_names}"
        )

    if user_notes:
        lines = ["## USER NOTES (persistent — treat as ground truth)"]
        for n in user_notes[:10]:
            date = (n.get("received_at") or "")[:10]
            lines.append(f"- ({date}) {n['note']}")
        sections.append("\n".join(lines))

    if recent_feedback:
        lines = ["## RECENT FEEDBACK (most recent first)"]
        for f in recent_feedback[:10]:
            content = (f.get("notes") or f.get("learnings") or "").strip()
            hours = f.get("actual_hours")
            hours_str = f" [{hours}h]" if hours is not None else ""
            lines.append(
                f"- [{f.get('phase', '')}]{hours_str} \"{content}\" "
                f"(task: {f.get('title', '')})"
            )
        sections.append("\n".join(lines))

    sections.append(skills_catalogue)

    if iteration_history:
        sections.append(
            "## ITERATION HISTORY (your previous proposals + user's responses)\n"
            + "\n".join(iteration_history)
        )

    sections.append(
        "## INSTRUCTION\n"
        "Generate the next Proposal as JSON. 3-5 options, all phase-aware. "
        "Always include a free-choice fallback. If the user has given iteration "
        "feedback above, incorporate it — do not propose the same thing again."
    )
    return "\n\n".join(sections)


class ConversationBrain(BaseBrain):
    brain_name = "conversation"

    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        skill_loader: SkillLoader,
    ):
        super().__init__(config, state)
        self.skill_loader = skill_loader

    def propose(
        self,
        bug_class_name: str,
        iteration_history: list[str] | None = None,
        force_phase: Phase | None = None,
    ) -> Proposal:
        """Generate options for the user. Cheap — no tools."""
        bc = self.state.get_bug_class(bug_class_name)
        if not bc:
            # Brand new bug class — propose creation + starting phase
            return self._propose_new_class(bug_class_name)

        # Existing bug class
        progress = self.state.get_all_phase_progress(bc["id"])
        recent_feedback = self.state.get_recent_feedback(bc["id"], limit=10)
        user_notes = self.state.get_user_notes(limit=10)
        mastered = self.state.get_all_mastered()

        # Hierarchy hint
        hierarchy_note = ""
        if not bc["is_leaf"]:
            children = self.state.get_children(bc["id"])
            if children:
                child_names = ", ".join(c["name"] for c in children)
                hierarchy_note = (
                    f"This is a PARENT class with {len(children)} children "
                    f"already created: {child_names}. Consider proposing the user "
                    f"pick one of these to drill, or add a new sibling child class."
                )
            else:
                hierarchy_note = (
                    "This is a PARENT class with no children yet. You should "
                    "enumerate the sub-classes most worth drilling within this "
                    "parent and offer them as options."
                )

        # If user used --<phase>, short-circuit propose and present that single phase
        if force_phase is not None:
            return self._forced_phase_proposal(bc, force_phase)

        catalogue = render_skills_catalogue(self.skill_loader)
        context = _build_context(
            bug_class=bc,
            progress=progress,
            recent_feedback=recent_feedback,
            user_notes=user_notes,
            mastered=mastered,
            hierarchy_note=hierarchy_note,
            iteration_history=iteration_history or [],
            skills_catalogue=catalogue,
        )

        raw = self._single_turn(
            model=self.config.llm.conversation_model,
            system=SYSTEM_PROMPT,
            user_message=context,
            max_tokens=2048,
        )
        data = self._parse_json_response(raw)
        return Proposal.model_validate(data)

    # ------------------------------------------------------------------

    def _propose_new_class(self, name: str) -> Proposal:
        """Heuristic proposal for a brand new bug class — no model call."""
        return Proposal(
            bug_class=name,
            context_summary=(
                f"'{name}' is a brand new bug class for you. You have no prior "
                f"resources consumed and no phase progress yet."
            ),
            options=[
                ProposalOption(
                    label=f"Start learn phase on {name}",
                    phase=Phase.LEARN,
                    description=(
                        "Drain ALL foundational theory from HackTricks, PortSwigger, "
                        "OWASP guides, cheat sheets, and foundational papers."
                    ),
                    rationale=(
                        "Standard entry point. The mastery loop forbids skipping "
                        "phases — even known concepts benefit from a structured drain."
                    ),
                ),
                ProposalOption(
                    label="Treat as a parent class (enumerate sub-classes)",
                    phase=None,
                    description=(
                        f"Only choose this if '{name}' is a broad category. Reply "
                        f"with which sub-class you want to drill."
                    ),
                    rationale=(
                        "Useful for parent classes like 'client-side web bugs'."
                    ),
                ),
                ProposalOption(
                    label="Free choice — describe what you want",
                    phase=None,
                    description=(
                        "Tell me exactly what phase + scope you want, in your own "
                        "words. I'll iterate until you're happy."
                    ),
                    rationale="Your final authority overrides any suggestion.",
                ),
            ],
            free_text_invitation="Pick a number or describe what you want.",
        )

    def _forced_phase_proposal(
        self,
        bug_class: dict[str, Any],
        phase: Phase,
    ) -> Proposal:
        """User specified `--<phase>` flag — surface that as the only option."""
        label_extras = ""
        if phase == Phase.RESEARCH:
            label_extras = (
                " Pick a research sub-mode (1=gap analysis, 2=bypass hunting, "
                "3=draft generation) or describe what you want."
            )

        return Proposal(
            bug_class=bug_class["name"],
            context_summary=(
                f"You requested {phase.value} phase for '{bug_class['name']}'. "
                f"Confirm to fire the planner, or push back with iteration."
            ),
            options=[
                ProposalOption(
                    label=f"Run {phase.value} phase now",
                    phase=phase,
                    description=(
                        f"Plan a session in the {phase.value} phase for "
                        f"'{bug_class['name']}'.{label_extras}"
                    ),
                    rationale="You explicitly requested this phase via the CLI flag.",
                ),
                ProposalOption(
                    label="Free choice — describe what you want instead",
                    phase=None,
                    description=(
                        "Override the phase flag with a different direction in "
                        "natural language."
                    ),
                    rationale="Your final authority.",
                ),
            ],
            free_text_invitation="Type 1 to confirm, or describe a change.",
        )


# ---------------------------------------------------------------------------
# Confirmation parsing — turns the user's free-text reply into a structured
# direction the planner can act on.
# ---------------------------------------------------------------------------


CONFIRM_SYSTEM_PROMPT = """\
You are the confirmation parser. Given the most recent Proposal (with N options) \
and the user's natural-language reply, decide ONE of:
  1. confirm — user accepted one option (or described an equivalent direction)
  2. iterate — user wants a different proposal (their reply is feedback)
  3. abort  — user wants to stop

If confirming, identify the phase + research_mode (if applicable) and a target \
hours value (default 3.0 if not stated).

Output ONLY JSON:
{
  "action": "confirm|iterate|abort",
  "phase": "learn|examples|practice|execute|research|null",
  "research_mode": "gap_analysis|bypass_hunting|draft_generation|null",
  "target_hours": 3.0,
  "iteration_feedback": "user's feedback summarized (only for action=iterate)"
}
"""


class ConfirmationDecision:
    """Lightweight container for the parser output."""

    def __init__(
        self,
        action: str,
        phase: Phase | None = None,
        research_mode: ResearchMode | None = None,
        target_hours: float = 3.0,
        iteration_feedback: str = "",
    ):
        self.action = action
        self.phase = phase
        self.research_mode = research_mode
        self.target_hours = target_hours
        self.iteration_feedback = iteration_feedback


def parse_confirmation(
    brain: ConversationBrain,
    proposal: Proposal,
    user_reply: str,
) -> ConfirmationDecision:
    """Parse a free-text reply into confirm/iterate/abort."""
    reply = user_reply.strip().lower()

    # Cheap shortcuts before calling the model
    if reply in ("q", "quit", "exit", "abort", "stop", "cancel"):
        return ConfirmationDecision(action="abort")

    if reply.isdigit():
        idx = int(reply) - 1
        if 0 <= idx < len(proposal.options):
            opt = proposal.options[idx]
            if opt.phase is None:
                return ConfirmationDecision(
                    action="iterate",
                    iteration_feedback=opt.label,
                )
            return ConfirmationDecision(
                action="confirm",
                phase=opt.phase,
                target_hours=3.0,
            )

    # Free text — model decides
    options_text = "\n".join(
        f"  {i + 1}. [{opt.phase or 'free'}] {opt.label} — {opt.description}"
        for i, opt in enumerate(proposal.options)
    )
    user_msg = (
        f"## CURRENT PROPOSAL\nBug class: {proposal.bug_class}\n\n"
        f"Options offered:\n{options_text}\n\n"
        f"## USER REPLY\n{user_reply}\n\n"
        f"Parse and return JSON."
    )
    raw = brain._single_turn(
        model=brain.config.llm.conversation_model,
        system=CONFIRM_SYSTEM_PROMPT,
        user_message=user_msg,
        max_tokens=512,
    )
    data = brain._parse_json_response(raw)

    action = data.get("action", "iterate")
    phase_str = data.get("phase")
    phase = None
    if phase_str and phase_str != "null":
        try:
            phase = Phase(phase_str)
        except ValueError:
            phase = None

    mode_str = data.get("research_mode")
    mode = None
    if mode_str and mode_str != "null":
        try:
            mode = ResearchMode(mode_str)
        except ValueError:
            mode = None

    return ConfirmationDecision(
        action=action,
        phase=phase,
        research_mode=mode,
        target_hours=float(data.get("target_hours", 3.0) or 3.0),
        iteration_feedback=data.get("iteration_feedback", "") or "",
    )
