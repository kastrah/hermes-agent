"""Exercise private handoffs over HTTP and the existing encrypted vault path."""
import asyncio
import json
import secrets
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gateway.secure_login import SecureLoginService

BASE = "https://zuri.example.ts.net:8443"
OWNER = "owner@example.test"
HEADERS = {"Host": "zuri.example.ts.net:8443", "Tailscale-User-Login": OWNER, "Origin": BASE}


def create(service, current=lambda: True, profile="zuri"):
    return service.create(origin="https://accounts.example.test", profile_home=profile,
                          session_key="agent:zuri:discord:dm:1", actor="1", owner_login=OWNER,
                          is_current=current)


async def claim(client, token, headers=None):
    response = await client.post("/claim", json={"token": token}, headers=headers or HEADERS)
    if response.status != 200:
        return response, {}
    body = await response.json()
    return response, {**HEADERS, "X-CSRF-Token": body["csrf"],
                      "Cookie": "__Host-zuri-login=" + response.cookies["__Host-zuri-login"].value}


@pytest.mark.asyncio
async def test_private_http_save_single_use_and_secret_free_response():
    service = SecureLoginService(BASE)
    token, entry, url = create(service)
    password = secrets.token_urlsafe(40)
    async with TestClient(TestServer(service.application())) as client:
        preview = await client.get("/", headers=HEADERS)
        assert preview.status == 200
        assert not entry.result.done()
        assert token not in await preview.text()
        response, headers = await claim(client, token)
        assert response.status == 200
        assert response.cookies["__Host-zuri-login"]["httponly"]
        saved = await client.post("/save", json={"identifier": "test@example.test", "password": password}, headers=headers)
        assert saved.status == 200
        assert password not in await saved.text()
        assert saved.headers["Cache-Control"] == "no-store"
        answer = await entry.result
        assert secrets.compare_digest(answer["password"], password)
        answer.clear()
        replay, _ = await claim(client, token)
        assert replay.status == 410
        assert not service.pending
        assert password not in url


@pytest.mark.asyncio
async def test_owner_csrf_host_and_expiry_fail_closed():
    service = SecureLoginService(BASE)
    token, entry, _ = create(service)
    async with TestClient(TestServer(service.application())) as client:
        for bad in ({**HEADERS, "Tailscale-User-Login": "other@example.test"},
                    {**HEADERS, "Origin": "https://evil.test"}, {**HEADERS, "Host": "evil.test"}):
            response, _ = await claim(client, token, bad)
            assert response.status in (403, 410)
        _, headers = await claim(client, token)
        bad_csrf = {**headers, "X-CSRF-Token": "wrong"}
        response = await client.post("/save", json={"identifier": "a", "password": "b"}, headers=bad_csrf)
        assert response.status == 403
        assert not entry.result.done()
        entry.expires = 0
        response = await client.post("/save", json={"identifier": "a", "password": "b"}, headers=headers)
        assert response.status == 410
    service.cancel(token)
    assert await entry.result is None


@pytest.mark.asyncio
async def test_profile_requests_do_not_share_cookies_and_cancel_releases_waiter():
    service = SecureLoginService(BASE)
    token, zuri, _ = create(service)
    other, froggy, _ = create(service, profile="froggy")
    async with TestClient(TestServer(service.application())) as client:
        _, headers = await claim(client, token)
        response = await client.post("/cancel", json={}, headers=headers)
        assert response.status == 200
        assert await zuri.result is None
        assert not froggy.result.done()
        response = await client.post("/save", json={"identifier": "a", "password": "b"}, headers=headers)
        assert response.status == 403
    await service.close()
    assert await froggy.result is None


@pytest.mark.asyncio
async def test_cancelled_turn_cannot_submit():
    service = SecureLoginService(BASE)
    live = [True]
    token, entry, _ = create(service, current=lambda: live[0])
    async with TestClient(TestServer(service.application())) as client:
        _, headers = await claim(client, token)
        live[0] = False
        response = await client.post("/save", json={"identifier": "a", "password": "b"}, headers=headers)
        assert response.status == 410
    service.cancel(token)
    assert await entry.result is None


def test_login_callback_does_not_enable_master_password_prompt():
    from agent.vault_backends import unlock
    unlock.set_save_login_prompt_callback(lambda *_: None)
    try:
        with patch("tools.approval_context._no_user_can_answer", return_value=False):
            assert unlock.can_prompt_here("login")
            assert not unlock.can_prompt_here("unlock")
        with patch("tools.approval_context._no_user_can_answer", return_value=True):
            assert not unlock.can_prompt_here("login")
    finally:
        unlock.set_save_login_prompt_callback(None)


@pytest.mark.parametrize("changed_origin,live", [(True, True), (False, False)])
def test_tool_refuses_changed_origin_or_cancel_before_vault_write(tmp_path, changed_origin, live):
    from agent.vault_store import VaultStore
    from agent.vault_backends import unlock
    from tools import browser_vault_tool as tool
    store = VaultStore(base_dir=tmp_path / "vault")
    answer = {"identifier": "test@example.test", "password": secrets.token_urlsafe(40), "_is_current": lambda: live}
    unlock.set_save_login_prompt_callback(lambda *_: answer)
    origins = ["https://accounts.example.test", "https://different.test" if changed_origin else "https://accounts.example.test"]
    try:
        with patch.object(tool, "_focus_bound_origin"), patch.object(tool, "_current_page_origin", side_effect=origins), \
                patch("tools.approval_context._no_user_can_answer", return_value=False), \
                patch("agent.vault_store.get_vault_store", return_value=store):
            result = json.loads(tool.browser_vault_save_login(task_id="test"))
        assert result["error_type"] == "save_cancelled"
        assert store.list_items() == []
        assert not answer
    finally:
        unlock.set_save_login_prompt_callback(None)


def test_tool_saves_encrypted_then_fills_without_password_in_result(tmp_path):
    from agent.vault_store import VaultStore
    from agent.vault_backends import unlock
    from tools import browser_vault_tool as tool
    store = VaultStore(base_dir=tmp_path / "vault")
    password = secrets.token_urlsafe(40)
    answer = {"identifier": "test@example.test", "password": password, "_is_current": lambda: True}
    unlock.set_save_login_prompt_callback(lambda *_: answer)
    try:
        with patch.object(tool, "_focus_bound_origin"), \
                patch.object(tool, "_current_page_origin", return_value="https://accounts.example.test"), \
                patch("tools.approval_context._no_user_can_answer", return_value=False), \
                patch("agent.vault_store.get_vault_store", return_value=store), \
                patch.object(tool, "browser_vault_fill", return_value='{"success":true}') as fill:
            output = tool.browser_vault_save_login(task_id="test")
        assert json.loads(output)["success"]
        assert password not in output
        assert password.encode() not in (tmp_path / "vault" / "vault.json.enc").read_bytes()
        assert not answer
        fill.assert_called_once()
    finally:
        unlock.set_save_login_prompt_callback(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["api_key", "token"])
async def test_key_token_form_and_encrypted_handle_only_storage(tmp_path, kind):
    from agent.vault_store import VaultStore
    from gateway.run_turn_secure_login import _secret_request, request_secret
    service = SecureLoginService(BASE)
    token, entry, _ = service.create(origin="", profile_home="zuri", session_key="s", actor="1",
                                     owner_login=OWNER, is_current=lambda: True, kind=kind, label="Example service")
    secret = secrets.token_urlsafe(40)
    async with TestClient(TestServer(service.application())) as client:
        response, headers = await claim(client, token)
        assert (await response.json())["kind"] == kind
        saved = await client.post("/save", json={"identifier": "", "password": secret}, headers=headers)
        assert saved.status == 200
        answer = await entry.result
    store = VaultStore(base_dir=tmp_path / "vault")
    context = _secret_request.set(lambda *_: answer)
    try:
        with patch("agent.vault_store.get_vault_store", return_value=store):
            output = request_secret(kind, "Example service")
        meta = json.loads(output)
        assert meta["success"]
        assert secret not in output
        assert secret.encode() not in (tmp_path / "vault" / "vault.json.enc").read_bytes()
        assert store.get_meta(meta["handle"]).kind == kind
        assert not answer
    finally:
        _secret_request.reset(context)


def test_secret_request_without_live_gateway_is_refused():
    from gateway.run_turn_secure_login import request_secret
    assert not json.loads(request_secret("api_key", "Example service"))["success"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["discord", "photon"])
async def test_gateway_prompt_routes_same_conversation_and_clears_callback(tmp_path, platform):
    from gateway.config import Platform
    from gateway.turn_context import TurnContext
    from gateway.run_turn_secure_login import secure_login_turn
    from agent.vault_backends import unlock
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.thread_context import propagate_context_to_thread
    delivered = asyncio.Event()
    sent = []
    service = SecureLoginService(BASE)

    async def send(**kwargs):
        sent.append(kwargs)
        delivered.set()
        return SimpleNamespace(success=True)

    adapter = SimpleNamespace(send=send)
    runner = SimpleNamespace(_secure_login_service=service, _delivery_adapter_for=lambda source: adapter)
    source = SimpleNamespace(platform=Platform(platform), user_id="1", is_bot=False, chat_id="chat")
    ctx = TurnContext(source=source, run_generation=1, session_key="agent:zuri:" + platform + ":thread:chat",
                      user_config={"secure_login": {"enabled": True, "base_url": BASE, "owner_login": OWNER,
                                   "allowed_users": {platform: ["1"]}}}, _run_still_current=lambda: True,
                      _status_thread_metadata={"thread_id": "thread"})
    loop = asyncio.get_running_loop()
    turn = SimpleNamespace(_ctx=ctx, _runner=runner, _agent_interrupted=lambda: False,
                           _close_native_stream_boundary=lambda *a, **kw: True,
                           _schedule=lambda coro, *_: asyncio.run_coroutine_threadsafe(coro, loop))

    def worker():
        with secure_login_turn(turn):
            assert unlock.can_prompt_here("login")
            answer = unlock.get_save_login_prompt_callback()("https://accounts.example.test", "site")
            assert answer and answer["identifier"] == "test@example.test"
            answer.clear()
        assert unlock.get_save_login_prompt_callback() is None

    scope = set_hermes_home_override(tmp_path / "zuri")
    try:
        async def no_start():
            return None
        with patch.object(service, "start", new=no_start):
            job = asyncio.create_task(asyncio.to_thread(propagate_context_to_thread(worker)))
            await asyncio.wait_for(delivered.wait(), 5)
            assert sent[0]["chat_id"] == "chat"
            assert sent[0]["metadata"]["thread_id"] == "thread"
            token = sent[0]["metadata"]["_secure_vault_link"].split("#")[1]
            entry = service.pending[token]
            assert entry.profile_home == str(tmp_path / "zuri")
            async with TestClient(TestServer(service.application())) as client:
                _, headers = await claim(client, token)
                response = await client.post("/save", headers=headers,
                                             json={"identifier": "test@example.test", "password": secrets.token_urlsafe(40)})
                assert response.status == 200
            await asyncio.wait_for(job, 5)
            assert not service.pending
    finally:
        reset_hermes_home_override(scope)
