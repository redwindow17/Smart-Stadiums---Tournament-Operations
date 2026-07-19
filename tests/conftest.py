"""Shared fixtures. Tests always run against the offline engine (empty API
key) so the suite is deterministic and needs no network or secrets."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="",
        model="claude-opus-4-8",
        rate_limit_per_minute=100,
        max_message_length=1000,
        max_history_turns=6,
        request_timeout_seconds=5.0,
    )
    base.update(overrides)
    return Settings(**base)


# Fixed instants relative to the sample fixtures (final at MetLife kicks off
# 2026-07-19T19:00Z) so crowd phases are stable in every test run.
INGRESS_AT_METLIFE = datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc)
QUIET_EVERYWHERE = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(make_settings()))


@pytest.fixture()
def strict_client() -> TestClient:
    """Client with a tiny rate limit for throttling tests."""
    return TestClient(create_app(make_settings(rate_limit_per_minute=3)))
