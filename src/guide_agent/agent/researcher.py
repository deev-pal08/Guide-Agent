"""Researcher agent — runs the research phase with Opus.

Wraps PlannerBrain with three key differences:
  1. Uses the Opus research model
  2. Loads the 'research' skill body for the system prompt
  3. The planner-loop instructions tell the model to call read_skill_reference
     for the matching sub-mode (GAP_ANALYSIS.md, BYPASS_HUNTING.md, or
     DRAFT_GENERATION.md) before generating output.

Conceptually identical to a planner run but with the research skill +
explicit sub-mode steering injected into the user message.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from guide_agent.agent.planner import PlannerBrain
from guide_agent.config import AppConfig
from guide_agent.models import Phase, Plan, ResearchMode
from guide_agent.skills.loader import SkillLoader
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


SUB_MODE_TO_REFERENCE = {
    ResearchMode.GAP_ANALYSIS: "GAP_ANALYSIS.md",
    ResearchMode.BYPASS_HUNTING: "BYPASS_HUNTING.md",
    ResearchMode.DRAFT_GENERATION: "DRAFT_GENERATION.md",
}


class ResearcherBrain(PlannerBrain):
    """Research-phase planner — Opus + research skill + sub-mode reference."""

    brain_name = "researcher"

    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        skill_loader: SkillLoader,
    ):
        super().__init__(config, state, skill_loader)
        # Active sub-mode for the in-flight research call. Set by research()
        # before calling plan(); read by _build_user_context().
        self._active_research_mode: ResearchMode | None = None

    def research(
        self,
        bug_class_id: int,
        bug_class_name: str,
        research_mode: ResearchMode,
        target_hours: float,
        date: str | None = None,
        fresh_fetch: bool = False,
    ) -> Plan:
        """Generate a research-phase plan with the appropriate sub-mode."""
        date = date or datetime.now(UTC).strftime("%Y-%m-%d")
        # Temporarily swap the model used by the planner loop AND record the
        # active sub-mode so _build_user_context can pick it up.
        original_model = self.config.llm.planner_model
        self.config.llm.planner_model = self.config.llm.research_model
        self._active_research_mode = research_mode

        try:
            plan = self.plan(
                bug_class_id=bug_class_id,
                bug_class_name=bug_class_name,
                phase=Phase.RESEARCH,
                target_hours=target_hours,
                date=date,
                research_mode=research_mode,
                skill_override="research",
                fresh_fetch=fresh_fetch,
            )
        finally:
            self.config.llm.planner_model = original_model
            self._active_research_mode = None

        return plan

    # The planner loop will load the 'research' SKILL.md as the active skill.
    # The skill instructions explicitly direct the model to call
    # read_skill_reference("research", "<MODE>.md") before composing output —
    # we inject which mode below by tweaking the user context.

    def _build_user_context(
        self,
        bug_class_id: int,
        bug_class_name: str,
        phase: Phase,
        target_hours: float,
        date: str,
        fresh_fetch: bool = False,
    ) -> str:
        base = super()._build_user_context(
            bug_class_id=bug_class_id,
            bug_class_name=bug_class_name,
            phase=phase,
            target_hours=target_hours,
            date=date,
            fresh_fetch=fresh_fetch,
        )
        # Use the in-flight research mode set by research() — NOT the latest
        # plan from the DB, which would leak the previous run's sub-mode.
        mode = self._active_research_mode
        ref_filename = SUB_MODE_TO_REFERENCE.get(mode) if mode else None

        if ref_filename:
            base += (
                f"\n\n## RESEARCH SUB-MODE\n"
                f"This run is in sub-mode '{mode.value}'. "
                f"You MUST call read_skill_reference("
                f"skill_name='research', filename='{ref_filename}') in your "
                f"first turn to load the methodology for this sub-mode before "
                f"generating output."
            )
        else:
            base += (
                "\n\n## RESEARCH SUB-MODE\n"
                "No sub-mode set — default to gap_analysis. Call "
                "read_skill_reference('research', 'GAP_ANALYSIS.md')."
            )
        return base
