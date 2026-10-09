from argparse import ArgumentParser
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.platforms.event import ProcessingOutcome
from plugins.platforms.photon.cli import register_cli
from plugins.platforms.photon.native_actions import build_request
from plugins.platforms.photon import adapter as module
from gateway.config import PlatformConfig


def test_native_cli_uses_profile_sidecar_contract():
    parser = ArgumentParser()
    register_cli(parser)
    args = parser.parse_args(["native", "effect", "--space", "chat", "--text", "done",
                              "--effect", "confetti", "--message-id", "anchor"])
    route, body = build_request(args)
    assert route == "/send-effect"
    assert body["replyToMessageId"] == "anchor"
    with pytest.raises(ValueError):
        build_request(parser.parse_args(["native", "edit", "--space", "chat"]))


@pytest.mark.asyncio
async def test_presence_retries_failure_and_refreshes_before_expiry(monkeypatch):
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test")
    adapter = module.PhotonAdapter(PlatformConfig(enabled=True))
    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    adapter._sidecar_try = AsyncMock(side_effect=[False, True, True, True])
    await adapter.send_typing("chat")
    await adapter.send_typing("chat")  # failure must not consume the cooldown
    now[0] += 2
    await adapter.send_typing("chat")
    await adapter.stop_typing("chat")
    assert [call.args[1]["state"] for call in adapter._sidecar_try.call_args_list] == [
        "start", "start", "start", "stop"]
    assert "chat" not in adapter._typing_last_sent


@pytest.mark.asyncio
async def test_cancelled_reaction_replaces_without_removal(monkeypatch):
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test")
    monkeypatch.setenv("PHOTON_REACTIONS", "true")
    adapter = module.PhotonAdapter(PlatformConfig(enabled=True))
    adapter._sidecar_try = AsyncMock(return_value=True)
    event = SimpleNamespace(source=SimpleNamespace(chat_id="chat"), message_id="target")
    await adapter.on_processing_complete(event, ProcessingOutcome.CANCELLED)
    assert [call.args[0] for call in adapter._sidecar_try.call_args_list] == ["/typing", "/react"]
    assert adapter._sidecar_try.call_args_list[-1].args[1]["emoji"] == "⏹️"
