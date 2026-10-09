"""Routine notices can be silent without suppressing input or actionable warnings."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from gateway.display_config import resolve_display_setting

pytestmark = pytest.mark.usefixtures("unit_bootstrap")

@pytest.mark.parametrize("setting", ["busy_ack_enabled", "compression_deferred_notifications"])
def test_notice_overrides_are_platform_scoped(setting):
    cfg = {"display": {"platforms": {"photon": {setting: False}}}}
    assert resolve_display_setting(cfg, "photon", setting) is False
    assert resolve_display_setting(cfg, "telegram", setting) is True
    assert resolve_display_setting({}, "photon", setting) is True

@pytest.mark.asyncio
async def test_silent_busy_notice_still_delivers_correction(monkeypatch):
    import gateway.run as gr
    from tests.gateway.test_busy_session_ack import _make_runner, _make_adapter, _make_event
    from gateway.platforms.base import build_session_key
    monkeypatch.setattr(gr, "_load_gateway_config", lambda: {
        "display": {"platforms": {"telegram": {"busy_ack_enabled": False}}}})
    monkeypatch.delenv("HERMES_GATEWAY_BUSY_ACK_ENABLED", raising=False)
    runner, _ = _make_runner()
    runner._busy_input_mode = "interrupt"
    adapter = _make_adapter()
    event = _make_event("use six people")
    key = build_session_key(event.source)
    agent = MagicMock()
    runner._running_agents[key] = agent
    runner.adapters[event.source.platform] = adapter
    assert await runner._handle_active_session_busy_message(event, key) is True
    agent.interrupt.assert_called_once_with("use six people")
    adapter._send_with_retry.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_turnhold_notice_does_not_change_compression_cleanup(monkeypatch, enabled):
    import gateway.run as gr
    from gateway.run_turn import GatewayTurnMixin
    monkeypatch.setattr(gr, "_load_gateway_config", lambda: {
        "display": {"platforms": {"telegram": {"compression_deferred_notifications": enabled}}}})
    monkeypatch.setattr(gr, "_record_hygiene_cooldown", MagicMock())
    runner = SimpleNamespace(
        _hmwa_hygiene_cancel_or_adopt=AsyncMock(return_value=None),
        _hmwa_hygiene_stamp=MagicMock(),
        _hmwa_hygiene_notify=AsyncMock())
    attempt = SimpleNamespace(commit_fence=SimpleNamespace(commit_watermark_fenced=False),
                              agent=MagicMock(), wait_started=time.monotonic(), meta={})
    source = SimpleNamespace(platform=gr.Platform.TELEGRAM)
    try:
        raise RuntimeError("turn hold")
    except RuntimeError:
        with pytest.raises(RuntimeError, match="turn hold"):
            await GatewayTurnMixin._hmwa_hygiene_on_turn_hold(
                runner, attempt, SimpleNamespace(), SimpleNamespace(session_id="test"), "key", source)
    runner._hmwa_hygiene_cancel_or_adopt.assert_awaited_once()
    runner._hmwa_hygiene_stamp.assert_called_once()
    assert runner._hmwa_hygiene_notify.await_count == int(enabled)

@pytest.mark.asyncio
async def test_silent_deferred_notice_does_not_hide_actionable_warning(monkeypatch):
    import gateway.run as gr
    from gateway.run_turn import GatewayTurnMixin
    monkeypatch.setattr(gr, "_load_gateway_config", lambda: {
        "display": {"platforms": {"telegram": {"compression_deferred_notifications": False}}}})
    adapter = SimpleNamespace(emit_warning=AsyncMock())
    runner = SimpleNamespace(_delivery_adapter_for=lambda source: adapter)
    source = SimpleNamespace(platform=gr.Platform.TELEGRAM, chat_id="test-chat")
    await GatewayTurnMixin._hmwa_hygiene_notify(runner, source, {}, "Compression failed", "failure")
    adapter.emit_warning.assert_awaited_once_with(
        "test-chat", "Compression failed", metadata={}, logical_platform=gr.Platform.TELEGRAM)
