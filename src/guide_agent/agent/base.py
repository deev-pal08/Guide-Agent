"""Shared API call infrastructure for Guide Agent brains.

All brains (Conversation, Planner, Researcher) inherit from BaseBrain to
get:
  - Retried, instrumented Anthropic client calls
  - Cost tracking accumulated per-brain in state.meta
  - JSON response parsing with markdown-fence and brace-recovery fallbacks
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from guide_agent.config import AppConfig
from guide_agent.state.store import StateStore

logger = logging.getLogger(__name__)


class GuideParseError(Exception):
    """Raised when a brain's response cannot be parsed as valid JSON."""


class BaseBrain:
    brain_name: str = "base"

    # Public Anthropic API endpoint. We pin this explicitly to bypass any
    # shell-set ANTHROPIC_BASE_URL (e.g. Meta's local Vertex proxy) so
    # guide-agent always hits the canonical API the rest of the user's
    # personal agents use.
    _PUBLIC_API_URL = "https://api.anthropic.com"

    def __init__(self, config: AppConfig, state: StateStore):
        self.config = config
        self.state = state
        self._client = anthropic.Anthropic(
            api_key=config.llm.api_key,
            base_url=self._PUBLIC_API_URL,
        )

    # ------------------------------------------------------------------
    # API call (retried)
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(anthropic.APIStatusError),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _call_claude(self, **kwargs: Any) -> Any:
        return self._client.messages.create(**kwargs)

    # ------------------------------------------------------------------
    # Usage / cost tracking
    # ------------------------------------------------------------------

    def _log_usage(self, response: Any, model_name: str) -> None:
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        logger.info(
            "API usage [%s/%s] — input: %d tokens, output: %d tokens",
            self.brain_name, model_name, input_tokens, output_tokens,
        )
        self._track_cost(input_tokens, output_tokens)

    def _track_cost(self, input_tokens: int, output_tokens: int) -> None:
        key = f"tokens_{self.brain_name}"
        raw = self.state.get_meta(key)
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"input": 0, "output": 0, "calls": 0}
        else:
            data = {"input": 0, "output": 0, "calls": 0}
        data["input"] += input_tokens
        data["output"] += output_tokens
        data["calls"] += 1
        self.state.set_meta(key, json.dumps(data))

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Extract JSON from a model response, handling fences and stray text."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            start = 1
            end = len(lines)
            for i in range(1, len(lines)):
                if lines[i].strip() == "```":
                    end = i
                    break
            text = "\n".join(lines[start:end])

        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            # Fallback: extract first { … last } block
            start_idx = text.find("{")
            end_idx = text.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                try:
                    return json.loads(text[start_idx:end_idx], strict=False)
                except json.JSONDecodeError:
                    pass
            logger.error("Failed to parse JSON: %s", text[:500])
            raise GuideParseError(
                f"[{self.brain_name}] Failed to parse JSON. "
                f"Raw text (first 500 chars): {text[:500]}"
            ) from None

    # ------------------------------------------------------------------
    # Single-turn convenience
    # ------------------------------------------------------------------

    def _single_turn(
        self,
        model: str,
        system: str,
        user_message: str,
        max_tokens: int = 8192,
    ) -> str:
        response = self._call_claude(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        self._log_usage(response, model)
        return response.content[0].text.strip()
