"""Claude-powered assistant engine (used when ANTHROPIC_API_KEY is set).

Efficiency notes:
- The system prompt is a frozen constant marked with ``cache_control`` so the
  Anthropic API serves it from prompt cache on repeat requests.
- The server pre-computes only the *relevant* grounding (route, facilities,
  crowd...) and ships it as compact JSON - one round trip, no tool loop, small
  token bills, and answers that cannot drift from venue facts.

Any failure (missing package, bad key, network, rate limit) raises
``EngineUnavailable`` and the caller falls back to the offline engine, so the
product never hard-fails on the AI dependency.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .prompts import OPS_SYSTEM_PROMPT, SYSTEM_PROMPT, build_ops_prompt, build_user_prompt

logger = logging.getLogger("stadiumiq.ai")


class EngineUnavailable(RuntimeError):
    """The Claude engine cannot serve this request; use the fallback."""


class ClaudeEngine:
    name = "claude"

    def __init__(self, settings: Settings):
        try:
            import anthropic  # imported lazily so the app runs without the package
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise EngineUnavailable("anthropic package not installed") from exc
        if not settings.anthropic_api_key:
            raise EngineUnavailable("no API key configured")
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.request_timeout_seconds,
            max_retries=1,
        )
        self._model = settings.model

    def _call(self, system: str, messages: list[dict[str, Any]], max_tokens: int) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
            )
        except Exception as exc:  # any SDK/network error -> graceful fallback
            logger.warning("Claude request failed, falling back to local engine: %s", exc)
            raise EngineUnavailable(str(exc)) from exc

        if response.stop_reason == "refusal":
            raise EngineUnavailable("model declined the request")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise EngineUnavailable("empty completion")
        return text

    def generate(
        self,
        message: str,
        context: dict[str, Any],
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        for turn in history or []:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": build_user_prompt(context, message)})
        return self._call(SYSTEM_PROMPT, messages, max_tokens=700)

    def ops_brief(self, snapshot: dict[str, Any], recommendations: list[dict[str, str]]) -> str:
        messages = [{"role": "user", "content": build_ops_prompt(snapshot, recommendations)}]
        return self._call(OPS_SYSTEM_PROMPT, messages, max_tokens=500)
