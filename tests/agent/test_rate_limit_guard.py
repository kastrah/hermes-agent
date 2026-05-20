import json
import time
from pathlib import Path

from agent import rate_limit_guard
from agent.rate_limit_guard import RateLimitStore


def test_rate_limit_store_records_reads_and_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_limit_guard, "_state_dir", lambda: str(tmp_path))
    store = RateLimitStore("demo", "model")

    store.record(headers={"retry-after": "60"})

    assert store.is_limited is True
    assert store.remaining is not None

    store.clear()

    assert store.is_limited is False


def test_rate_limit_store_uses_error_context_reset_at(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_limit_guard, "_state_dir", lambda: str(tmp_path))
    reset_at = time.time() + 120

    RateLimitStore("demo").record(error_context={"reset_at": reset_at})

    state_path = next(tmp_path.glob("*.json"))
    state = json.loads(state_path.read_text())
    assert state["reset_at"] == reset_at


def test_run_agent_wires_cross_session_rate_guard_into_provider_loop():
    loop_source = (Path(__file__).resolve().parents[2] / "agent/conversation_loop.py").read_text()
    helpers_source = (Path(__file__).resolve().parents[2] / "agent/chat_completion_helpers.py").read_text()

    assert "rate_limit_remaining(agent.provider, agent.model)" in loop_source
    assert "agent._try_activate_fallback(reason=FailoverReason.rate_limit)" in loop_source
    assert "record_rate_limit(" in loop_source
    assert "agent._capture_rate_limits(" in helpers_source
