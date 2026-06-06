"""Feedback parser — converts email reply text to structured TaskUpdate list.

Uses Claude Haiku to parse free-form replies like:
   "1: done 2.5h — learned about X
    2: skip — too easy
    3: done 1h
    general: today felt rushed"

into structured EmailFeedback objects.
"""

from __future__ import annotations

import logging
from typing import Any

from guide_agent.agent.base import BaseBrain
from guide_agent.config import AppConfig
from guide_agent.models import EmailFeedback
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


FEEDBACK_PROMPT = """\
You parse a user's email reply about today's task list into structured JSON.

The user references tasks by their 1-indexed number from the email. For each:
- status: done | skipped | in_progress | pending
- actual_hours: float (optional)
- notes: free-form notes
- learnings: what they learned (often blended with notes — keep both if ambiguous)

Common reply shapes:
  "1: done 2.5h — really helpful"
  "2: skip — too easy, give me harder next time"
  "3: done 1h"
  "1 done 30m"   (minutes — convert to hours)
  "completed 2"  (means task 2 was completed)

Anything that isn't a task-specific update goes in general_notes.

Output JSON ONLY:
{
  "task_updates": [
    {
      "task_id": 1,
      "status": "done",
      "actual_hours": 2.5,
      "notes": "really helpful",
      "learnings": ""
    }
  ],
  "general_notes": "any free-form text not tied to a specific task",
  "total_hours_reported": 2.5
}
"""


class FeedbackParser(BaseBrain):
    brain_name = "feedback_parser"

    def __init__(self, config: AppConfig, state: StateStore):
        super().__init__(config, state)

    def parse(self, email_body: str, task_count: int) -> EmailFeedback:
        prompt = (
            f"## TASK COUNT IN TODAY'S PLAN\n"
            f"{task_count} tasks (numbered 1 through {task_count}).\n\n"
            f"## USER REPLY\n{email_body}\n\n"
            f"Parse it into structured JSON now."
        )
        raw = self._single_turn(
            model=self.config.llm.conversation_model,
            system=FEEDBACK_PROMPT,
            user_message=prompt,
            max_tokens=1024,
        )
        data = self._parse_json_response(raw)
        return EmailFeedback.model_validate(data)


def apply_feedback(
    state: StateStore,
    feedback: EmailFeedback,
    plan_tasks: list[dict[str, Any]],
) -> int:
    """Apply parsed feedback to the state store. Returns count of tasks updated."""
    updated = 0
    for entry in feedback.task_updates:
        idx = entry.task_id - 1
        if idx < 0 or idx >= len(plan_tasks):
            logger.warning("Skipping out-of-range task_id %s", entry.task_id)
            continue
        task_row = plan_tasks[idx]
        db_id = task_row.get("id")
        if not db_id:
            continue

        state.update_task_status(
            task_id=db_id,
            status=entry.status.value,
            actual_hours=entry.actual_hours,
            learnings=entry.learnings,
        )
        state.log_feedback(
            task_id=db_id,
            status=entry.status.value,
            actual_hours=entry.actual_hours,
            notes=entry.notes,
            learnings=entry.learnings,
            source="email",
        )
        updated += 1

    if feedback.general_notes:
        state.append_user_note(feedback.general_notes)
        logger.info("Logged user note: %s", feedback.general_notes[:80])

    return updated
