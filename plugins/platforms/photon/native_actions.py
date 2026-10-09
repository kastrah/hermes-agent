"""Profile-scoped CLI access to the running Photon sidecar."""
from __future__ import annotations

import json
from pathlib import Path

_ROUTES = {"capabilities": "/capabilities", "poll": "/send-poll",
           "effect": "/send-effect", "edit": "/native", "contact-card": "/native",
           "background": "/native"}


def build_request(args):
    action = args.action
    body = {"action": action, "spaceId": args.space}
    if action != "capabilities" and not args.space:
        raise ValueError("--space is required")
    if action == "poll":
        if not args.text or not args.options or len(args.options) < 2:
            raise ValueError("poll requires --text and at least two --options")
        body.update(title=args.text, options=args.options)
    elif action == "effect":
        if not args.text or not args.effect:
            raise ValueError("effect requires --text and --effect")
        body.update(text=args.text, effect=args.effect, replyToMessageId=args.message_id)
    elif action == "edit":
        if not args.text or not args.message_id:
            raise ValueError("edit requires --text and --message-id")
        body.update(text=args.text, messageId=args.message_id)
    elif action == "background":
        if not args.clear:
            if not args.path or not Path(args.path).is_absolute() or not Path(args.path).is_file():
                raise ValueError("background requires --clear or an existing absolute --path")
            if Path(args.path).stat().st_size > 20 * 1024 * 1024:
                raise ValueError("background image exceeds 20 MB")
        body.update(path=args.path, clear=args.clear)
    return _ROUTES[action], body


def run(args):
    from .adapter import _standalone_token_from_record
    import httpx
    try:
        route, body = build_request(args)
        token, port, error = _standalone_token_from_record(8789)
        if error:
            raise ValueError(error)
        response = httpx.post(
            f"http://127.0.0.1:{port}{route}", json=body,
            headers={"X-Hermes-Sidecar-Token": token}, timeout=30)
        result = response.json()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if response.status_code == 200 and result.get("ok") else 1
    except (ValueError, httpx.HTTPError):
        print(json.dumps({"ok": False, "error": "Native action failed; check arguments and gateway logs."}))
        return 1
