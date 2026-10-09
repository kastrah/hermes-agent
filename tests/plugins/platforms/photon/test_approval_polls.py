"""Request-scoped, fail-closed tap approvals for Photon."""
import time
from unittest.mock import AsyncMock
import pytest
from gateway.platforms.base import SendResult
from tests.plugins.platforms.photon.test_poll_clarify import _make_adapter
from tools import approval
from tools.approval_gateway_wait import _ApprovalEntry

@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("PHOTON_NODE_BIN", "node")
    result = _make_adapter(monkeypatch)
    result._sidecar_send_poll = AsyncMock(return_value=SendResult(success=True, message_id="poll"))
    result.send = AsyncMock(return_value=SendResult(success=True))
    result.handle_message = AsyncMock()
    result.set_authorization_check(lambda user, kind, chat: user == "owner")
    monkeypatch.setattr(approval, "_gateway_queues", {})
    return result

async def prompt(adapter, request_id="wanted", **flags):
    return await adapter.send_exec_approval(
        "chat", "test command", "session", metadata={"approval_request_id": request_id}, **flags)

def vote(adapter, label="Approve once"):
    return {"pollTitle": next(iter(adapter._approval_polls)), "title": label, "selected": True}

@pytest.mark.asyncio
@pytest.mark.parametrize("label,expected", [("Approve once","once"), ("Deny","deny"),
    ("Approve for this session","session"), ("Approve permanently","always")])
async def test_vote_resolves_exact_request_once(adapter, label, expected):
    first = _ApprovalEntry({"request_id":"other"})
    target = _ApprovalEntry({"request_id":"wanted"})
    approval._gateway_queues["session"] = [first, target]
    assert (await prompt(adapter)).success
    options = adapter._sidecar_send_poll.call_args.args[2]
    assert options == ["Approve once", "Approve for this session", "Approve permanently", "Deny"]
    content = vote(adapter, label)
    assert await adapter._handle_approval_poll_vote("chat","owner","dm",content)
    assert target.result == expected and target.event.is_set()
    assert first.result is None and not first.event.is_set()
    await adapter._handle_approval_poll_vote("chat","owner","dm",content)
    assert first.result is None
    adapter.send.assert_awaited_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unauthorised", "unknown-auth", "wrong-chat", "expired",
                                   "deselected", "broader-choice", "withdrawn"])
async def test_invalid_vote_cannot_approve(adapter, case):
    entry = _ApprovalEntry({"request_id":"wanted"})
    approval._gateway_queues["session"] = [entry]
    await prompt(adapter)
    content = vote(adapter)
    chat, user = "chat", "owner"
    if case == "unauthorised": user = "stranger"
    if case == "unknown-auth": adapter.set_authorization_check(None)
    if case == "wrong-chat": chat = "elsewhere"
    if case == "expired":
        key = content["pollTitle"]
        adapter._approval_polls[key] = ("chat","session","wanted",time.monotonic()-1,
                                        adapter._approval_polls[key][-1])
    if case == "deselected": content["selected"] = False
    if case == "broader-choice": content["title"] = "Always"
    if case == "withdrawn":
        approval._gateway_queues["session"] = [_ApprovalEntry({"request_id":"newer"})]
    assert await adapter._handle_approval_poll_vote(chat,user,"dm",content)
    assert entry.result is None
    adapter.send.assert_not_awaited()
    for remaining in approval._gateway_queues.get("session", []):
        assert remaining.result is None

@pytest.mark.asyncio
async def test_missing_binding_and_send_failure_are_safe(adapter):
    assert not (await adapter.send_exec_approval("chat","cmd","session")).success
    adapter._sidecar_send_poll.assert_not_awaited()
    adapter._sidecar_send_poll.return_value = SendResult(success=False,error="offline")
    assert not (await prompt(adapter)).success
    assert not adapter._approval_polls

@pytest.mark.asyncio
async def test_inbound_approval_vote_never_becomes_agent_text(adapter):
    entry = _ApprovalEntry({"request_id":"wanted"})
    approval._gateway_queues["session"] = [entry]
    await prompt(adapter)
    await adapter._dispatch_inbound({"space":{"id":"chat","type":"dm"},
        "sender":{"id":"owner"}, "content":{"type":"poll_option", **vote(adapter)}})
    assert entry.result == "once"
    adapter.handle_message.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize("flags,expected", [
    ({"allow_session": False}, ["Approve once", "Deny"]),
    ({"allow_permanent": False}, ["Approve once", "Approve for this session", "Deny"]),
    ({"smart_denied": True}, ["Approve once", "Deny"]),
])
async def test_restricted_prompt_rejects_hidden_scope(adapter, flags, expected):
    entry = _ApprovalEntry({"request_id": "wanted"})
    approval._gateway_queues["session"] = [entry]
    await prompt(adapter, **flags)
    assert adapter._sidecar_send_poll.call_args.args[2] == expected
    content = vote(adapter, "Approve permanently")
    assert await adapter._handle_approval_poll_vote("chat", "owner", "dm", content)
    assert entry.result is None
    adapter.send.assert_not_awaited()
