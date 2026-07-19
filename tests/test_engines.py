"""Engine behaviour: the Claude adapter (against a stubbed SDK - no network)
and the Assistant's engine-fallback contract."""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.ai.claude_engine import CHAT_MAX_TOKENS, OPS_BRIEF_MAX_TOKENS, ClaudeEngine, EngineUnavailable
from app.services.assistant import Assistant

from .conftest import INGRESS_AT_METLIFE, make_settings

# ------------------------- stubbed anthropic SDK -------------------------


class _Block:
    def __init__(self, type_: str, text: str = ""):
        self.type = type_
        self.text = text


class _Response:
    def __init__(self, text: str = "Stubbed answer.", stop_reason: str = "end_turn", blocks: list | None = None):
        self.stop_reason = stop_reason
        self.content = blocks if blocks is not None else [_Block("text", text)]


@pytest.fixture()
def fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install a minimal stand-in for the `anthropic` module so ClaudeEngine
    can be exercised deterministically, with zero network access."""
    state: dict[str, Any] = {"outcome": _Response(), "calls": []}

    def create(**kwargs: Any) -> _Response:
        state["calls"].append(kwargs)
        outcome = state["outcome"]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    class Anthropic:
        def __init__(self, **kwargs: Any) -> None:
            state["client_kwargs"] = kwargs
            self.messages = types.SimpleNamespace(create=create)

    module = types.ModuleType("anthropic")
    module.Anthropic = Anthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return state


def _engine() -> ClaudeEngine:
    return ClaudeEngine(make_settings(anthropic_api_key="test-key"))


def test_engine_requires_api_key():
    with pytest.raises(EngineUnavailable):
        ClaudeEngine(make_settings())  # empty key


def test_generate_passes_prompt_cache_and_history(fake_anthropic):
    engine = _engine()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    reply = engine.generate("Where is Gate C?", {"venue": {"name": "Estadio Azteca"}}, history)

    assert reply == "Stubbed answer."
    call = fake_anthropic["calls"][0]
    assert call["max_tokens"] == CHAT_MAX_TOKENS
    # Frozen system prompt is marked for Anthropic prompt caching.
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    # History threads through, then the grounded prompt goes last.
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    assert "<visitor_message>" in call["messages"][-1]["content"]
    assert "Where is Gate C?" in call["messages"][-1]["content"]


def test_generate_ignores_non_text_blocks(fake_anthropic):
    fake_anthropic["outcome"] = _Response(blocks=[_Block("thinking", "internal"), _Block("text", "answer")])
    assert _engine().generate("q", {}) == "answer"


def test_refusal_raises_engine_unavailable(fake_anthropic):
    fake_anthropic["outcome"] = _Response(stop_reason="refusal")
    with pytest.raises(EngineUnavailable):
        _engine().generate("q", {})


def test_empty_completion_raises_engine_unavailable(fake_anthropic):
    fake_anthropic["outcome"] = _Response(blocks=[])
    with pytest.raises(EngineUnavailable):
        _engine().generate("q", {})


def test_sdk_error_raises_engine_unavailable(fake_anthropic):
    fake_anthropic["outcome"] = RuntimeError("connection reset")
    with pytest.raises(EngineUnavailable):
        _engine().generate("q", {})


def test_ops_brief_uses_ops_budget(fake_anthropic):
    _engine().ops_brief({"zones": []}, [])
    assert fake_anthropic["calls"][0]["max_tokens"] == OPS_BRIEF_MAX_TOKENS


# ------------------------- fallback contract -----------------------------


class _StubClaude:
    """Stands in for ClaudeEngine at the Assistant boundary."""

    name = "claude"

    def __init__(self, fail: bool):
        self.fail = fail

    def generate(self, message: str, context: dict, history: list | None = None) -> str:
        if self.fail:
            raise EngineUnavailable("simulated outage")
        return "claude reply"

    def ops_brief(self, snapshot: dict, recommendations: list) -> str:
        if self.fail:
            raise EngineUnavailable("simulated outage")
        return "claude brief"


def _assistant_with(stub: _StubClaude) -> Assistant:
    assistant = Assistant(make_settings())
    # Inject at the private seam deliberately: the fallback contract is what
    # we are testing, without importing any real SDK.
    assistant._claude = stub  # type: ignore[assignment]
    assistant._claude_disabled = False
    return assistant


def test_answer_uses_claude_when_it_succeeds():
    res = _assistant_with(_StubClaude(fail=False)).answer(
        message="hello", venue_id="azteca", at=INGRESS_AT_METLIFE
    )
    assert res["engine"] == "claude"
    assert res["reply"] == "claude reply"


def test_answer_falls_back_to_local_on_engine_failure():
    res = _assistant_with(_StubClaude(fail=True)).answer(
        message="hello", venue_id="azteca", at=INGRESS_AT_METLIFE
    )
    assert res["engine"] == "local"
    assert res["reply"]  # offline engine still produced a real answer


def test_ops_advisory_falls_back_to_local_on_engine_failure():
    ok = _assistant_with(_StubClaude(fail=False)).ops_advisory("azteca", at=INGRESS_AT_METLIFE)
    assert ok["engine"] == "claude" and ok["brief"] == "claude brief"

    degraded = _assistant_with(_StubClaude(fail=True)).ops_advisory("azteca", at=INGRESS_AT_METLIFE)
    assert degraded["engine"] == "local"
    assert "Phase:" in degraded["brief"]
