"""Application configuration, loaded once from environment variables.

No secrets are ever stored in code. `ANTHROPIC_API_KEY` is optional: without
it the app runs in deterministic offline demo mode so it can be evaluated
without any external account.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer env var defensively (bad values fall back to default)."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model: str
    rate_limit_per_minute: int
    max_message_length: int
    max_history_turns: int
    request_timeout_seconds: float


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        model=os.getenv("STADIUMIQ_MODEL", "claude-opus-4-8").strip() or "claude-opus-4-8",
        rate_limit_per_minute=_int_env("STADIUMIQ_RATE_LIMIT", 30),
        max_message_length=_int_env("STADIUMIQ_MAX_MESSAGE_LENGTH", 1000, minimum=10),
        max_history_turns=6,
        request_timeout_seconds=30.0,
    )
