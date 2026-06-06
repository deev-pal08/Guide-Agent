"""Resend-based email sender for the Guide Agent."""

from __future__ import annotations

import logging

import resend

from guide_agent.config import EmailConfig
from guide_agent.email.templates import render_plan_email, render_text_fallback
from guide_agent.models import Plan

logger = logging.getLogger(__name__)


class EmailSender:
    """Wraps Resend SDK with config + sensible defaults."""

    def __init__(self, config: EmailConfig):
        self.config = config
        if config.enabled:
            resend.api_key = config.api_key

    def send_plan(self, plan: Plan) -> str | None:
        """Send a plan as an HTML email. Returns the message id."""
        if not self.config.enabled:
            logger.info("Email disabled in config — skipping send")
            return None

        if not self.config.to_addresses:
            logger.warning("No to_addresses configured — skipping send")
            return None

        subject = self._subject(plan)
        html = render_plan_email(plan)
        text = render_text_fallback(plan)

        try:
            response = resend.Emails.send({
                "from": self.config.from_address,
                "to": self.config.to_addresses,
                "subject": subject,
                "html": html,
                "text": text,
            })
            mid = response.get("id") if isinstance(response, dict) else None
            logger.info("Plan email sent: %s (message_id=%s)", subject, mid)
            return mid
        except Exception:
            logger.exception("Failed to send plan email")
            return None

    def send_failure_notification(self, error_msg: str, bug_class: str) -> None:
        """Send a plain-text email when plan generation fails."""
        if not self.config.enabled or not self.config.to_addresses:
            return
        try:
            resend.Emails.send({
                "from": self.config.from_address,
                "to": self.config.to_addresses,
                "subject": f"[Guide] Plan generation failed — {bug_class}",
                "text": (
                    f"Guide failed to generate a plan for {bug_class}.\n\n"
                    f"Error:\n{error_msg}\n\n"
                    f"Re-run from the CLI when ready."
                ),
            })
        except Exception:
            logger.exception("Failed to send failure notification email")

    def _subject(self, plan: Plan) -> str:
        from datetime import datetime
        phase = plan.phase.value.upper()
        mode = (
            f" ({plan.research_mode.value})"
            if plan.research_mode is not None else ""
        )
        # Include HH:MM so re-runs of the same bug-class + phase on the
        # same day don't get threaded together by the mail client.
        timestamp = datetime.now().strftime("%H:%M")
        return (
            f"[Guide] {plan.date} {timestamp} — "
            f"{plan.bug_class_name} {phase}{mode}"
        )
