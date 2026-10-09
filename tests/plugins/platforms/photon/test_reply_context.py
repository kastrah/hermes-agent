"""Inbound Spectrum reply context reaches the gateway event contract."""
from __future__ import annotations

import asyncio

from gateway.config import PlatformConfig
from plugins.platforms.photon.adapter import PhotonAdapter


def _event(content, message_id="reply-msg-1"):
    return {
        "messageId": message_id,
        "space": {"id": "+155****4567", "type": "dm", "phone": "+155****4567"},
        "sender": {"id": "+155****4567"},
        "content": content,
    }


def test_native_reply_preserves_quoted_context(monkeypatch):
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    adapter = PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    captured = []

    async def handle(event):
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", handle)
    asyncio.run(adapter._dispatch_inbound(_event({
        "type": "reply",
        "content": {"type": "text", "text": "new answer"},
        "target": {
            "id": "source-msg-1",
            "text": "quoted source",
            "direction": "inbound",
            "senderId": "sender-1",
            "senderName": "Sender",
        },
    })))

    assert len(captured) == 1
    event = captured[0]
    assert event.text == "new answer"
    assert event.reply_to_message_id == "source-msg-1"
    assert event.reply_to_text == "quoted source"
    assert event.reply_to_author_id == "sender-1"
    assert event.reply_to_author_name == "Sender"
    assert event.reply_to_is_own_message is False


def test_reply_to_outbound_target_marks_own_without_cache(monkeypatch):
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    adapter = PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    captured = []

    async def handle(event):
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", handle)
    asyncio.run(adapter._dispatch_inbound(_event({
        "type": "reply",
        "content": {"type": "text", "text": "yes"},
        "target": {"id": "bot-msg-1", "text": "question", "direction": "outbound"},
    })))

    assert captured[0].reply_to_is_own_message is True


def test_reply_to_cached_target_uses_legacy_fallback(monkeypatch):
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    adapter = PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))
    adapter._sent_message_ids["bot-msg-1"] = 1.0
    captured = []

    async def handle(event):
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", handle)
    asyncio.run(adapter._dispatch_inbound(_event({
        "type": "reply",
        "content": {"type": "text", "text": "yes"},
        "target": {"id": "bot-msg-1", "text": "question"},
    })))

    assert captured[0].reply_to_is_own_message is True
