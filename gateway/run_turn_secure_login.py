"""Turn-scoped bridge from the existing vault prompt to the private web form."""
from contextlib import contextmanager
from concurrent.futures import TimeoutError
from contextvars import ContextVar
import asyncio
import json

from hermes_constants import get_hermes_home

_secret_request = ContextVar("secure_vault_request", default=None)
_credential_access = ContextVar("secure_vault_access", default=None)


def authenticated_request(handle, service):
    access = _credential_access.get()
    if access is None:
        return json.dumps({"success": False, "error": "Use your active authorised chat."})
    from tools.vault_credential_request import request
    current, services = access
    return request(handle, service, services, current)


async def request_login(turn, origin, config, *, kind="login", label=""):
    from gateway.secure_login import SecureLoginService
    ctx, runner = turn._ctx, turn._runner
    source = ctx.source
    from agent.tool_executor import _resolve_concurrent_tool_timeout, _resolve_sequential_tool_timeout
    deadlines = [v for v in (_resolve_concurrent_tool_timeout(), _resolve_sequential_tool_timeout())
                 if v is not None and v > 0]
    lifetime = min(300, min(deadlines, default=420) - 30)
    if lifetime < 30:
        return None  # A short configured tool deadline cannot safely host human input.
    service = getattr(runner, "_secure_login_service", None)
    if service is None:
        service = SecureLoginService(config["base_url"], port=int(config.get("port", 8874)))
        runner._secure_login_service = service
    if service.base_url != config["base_url"].rstrip("/"):
        return None  # One private service origin per gateway process.
    await service.start()
    current = lambda: not turn._agent_interrupted() and ctx._run_still_current()
    token, entry, url = service.create(
        origin=origin, profile_home=str(get_hermes_home()), session_key=ctx.session_key,
        actor=str(source.user_id), owner_login=config["owner_login"], is_current=current,
        kind=kind, label=label, ttl=lifetime)
    try:
        adapter = runner._delivery_adapter_for(source)
        if adapter is None:
            return None
        result = await adapter.send(
            chat_id=source.chat_id,
            content=f"Save {'login' if kind == 'login' else kind.replace('_', ' ')} securely for {origin or label}:\n{url}\n"
                    "Use your Tailscale connection. Never send the secret in chat.",
            reply_to=ctx.event_message_id,
            metadata={**(ctx._status_thread_metadata or {}), "_interim_send": True,
                      "_secure_vault_link": url})
        if not result.success:
            return None
        while service.live(entry):
            try:
                return await asyncio.wait_for(asyncio.shield(entry.result), timeout=0.5)
            except asyncio.TimeoutError:
                continue
        return entry.result.result() if entry.result.done() and current() else None
    finally:
        service.cancel(token)


def request_secret(kind, service):
    """Plugin entry point: only a live authorised gateway turn can obtain a form."""
    prompt = _secret_request.get()
    if kind not in ("api_key", "token") or not isinstance(service, str) or not service.strip():
        return json.dumps({"success": False, "error": "Choose api_key or token and name the service."})
    if prompt is None:
        return json.dumps({"success": False, "error": "Secure input needs your active authorised chat."})
    answer = prompt(kind, service.strip())
    if not answer:
        return json.dumps({"success": False, "error": "Secure input cancelled or expired."})
    try:
        if not answer["_is_current"]():
            return json.dumps({"success": False, "error": "The task ended. Secret not saved."})
        from agent.vault_store import get_vault_store
        from agent.redact import register_vault_redaction_value
        register_vault_redaction_value(answer["password"])
        meta = get_vault_store().add_item(kind, service.strip(), {"value": answer["password"]})
        return json.dumps({"success": True, "handle": meta.id, "kind": kind, "service": meta.label,
                           "note": "Encrypted in the vault. No secret value is returned or auto-filled."})
    except Exception:
        return json.dumps({"success": False, "error": "Could not save the secret securely."})
    finally:
        answer.clear()


@contextmanager
def secure_login_turn(turn):
    from agent.vault_backends.unlock import (
        get_save_login_prompt_callback, set_save_login_prompt_callback)
    from tools.approval_context import _no_user_can_answer
    ctx = turn._ctx
    config = (ctx.user_config or {}).get("secure_login", {})
    source = ctx.source
    platform = source.platform.value if source is not None else ""
    allowed = config.get("allowed_users", {}).get(platform, [])
    eligible = (config.get("enabled") is True and source is not None
                and platform in ("discord", "photon") and not source.is_bot
                and str(source.user_id) in [str(value) for value in allowed]
                and not _no_user_can_answer() and not ctx.scheduled_heartbeat
                and ctx.run_generation is not None and bool(ctx.session_key)
                and callable(ctx._run_still_current) and config.get("owner_login"))
    previous = get_save_login_prompt_callback()

    def wait(origin, *, kind="login", label=""):
        turn._close_native_stream_boundary("Secure input", reopen=True)
        future = turn._schedule(request_login(turn, origin, config, kind=kind, label=label), "Secure input could not start")
        if future is None:
            return None
        try:
            return future.result(timeout=320)
        except TimeoutError:
            future.cancel()
            return None
        except Exception:
            return None  # No exception, body or password is surfaced to the model.

    set_save_login_prompt_callback((lambda origin, _site: wait(origin)) if eligible else None)
    secret_token = _secret_request.set((lambda kind, label: wait("", kind=kind, label=label)) if eligible else None)
    access_token = _credential_access.set(
        (lambda: not turn._agent_interrupted() and ctx._run_still_current(),
         config.get("credential_services", {})) if eligible else None)
    try:
        yield
    finally:
        set_save_login_prompt_callback(previous)
        _secret_request.reset(secret_token)
        _credential_access.reset(access_token)
