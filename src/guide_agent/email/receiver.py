"""IMAP reply receiver for the Guide Agent.

Polls for replies to the most recent plan email, returns the body text(s).
The CLI then runs them through the feedback parser.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from typing import Any

from guide_agent.config import IMAPConfig

logger = logging.getLogger(__name__)


class EmailReceiver:
    def __init__(self, config: IMAPConfig):
        self.config = config

    def fetch_replies(
        self,
        since_date: str | None = None,
        from_address: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch replies from the configured inbox.

        Returns a list of dicts: {subject, from, body, received}.
        Caller is responsible for marking the messages read or archiving.
        """
        if not self.config.enabled:
            logger.info("IMAP disabled in config — skipping fetch")
            return []

        try:
            mail = imaplib.IMAP4_SSL(self.config.server, self.config.port)
            mail.login(self.config.email, self.config.password)
            mail.select(self.config.mailbox)

            # Build search query — subject contains [Guide] and is from us
            criteria = ['(SUBJECT "[Guide]")']
            if from_address:
                criteria.append(f'(FROM "{from_address}")')
            if since_date:
                # IMAP expects DD-MMM-YYYY
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(since_date[:10])
                    criteria.append(f'(SINCE "{dt.strftime("%d-%b-%Y")}")')
                except ValueError:
                    pass

            search_q = " ".join(criteria) if criteria else "ALL"
            status, data = mail.search(None, search_q)
            if status != "OK":
                logger.warning("IMAP search returned %s", status)
                mail.logout()
                return []

            msg_ids = data[0].split()
            replies: list[dict[str, Any]] = []
            for mid in msg_ids[-20:]:  # cap at last 20 results
                status, msg_data = mail.fetch(mid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, bytes):
                    continue
                msg = email.message_from_bytes(raw)
                body = _extract_body(msg)
                if not body:
                    continue
                replies.append({
                    "subject": msg.get("Subject", ""),
                    "from": msg.get("From", ""),
                    "body": _trim_quoted(body),
                    "received": msg.get("Date", ""),
                })

            mail.logout()
            logger.info("Fetched %d Guide reply emails", len(replies))
            return replies
        except Exception:
            logger.exception("Failed to fetch replies via IMAP")
            return []


def _extract_body(msg: email.message.Message) -> str:
    """Pull text/plain body if available, else fall back to text/html stripped."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        # fallback: take first text/html and strip
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    html = payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace",
                    )
                    return _strip_html(html)
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    return ""


def _strip_html(html: str) -> str:
    """Very dumb HTML strip — good enough for reply parsing."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _trim_quoted(body: str) -> str:
    """Trim quoted history from a reply — keep only the user's new text."""
    lines = body.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if stripped.startswith("On ") and "wrote:" in stripped:
            break
        if stripped.startswith("From: ") and "Sent: " not in stripped:
            # crude Outlook header detector
            break
        out.append(line)
    return "\n".join(out).strip()
