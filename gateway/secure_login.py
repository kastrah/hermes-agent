"""Private, owner-authenticated login handoffs; no secrets enter gateway messages.

Only expose this loopback service through Tailscale Serve, never Funnel. Serve
removes caller-supplied identity headers and supplies the authenticated login.
Local processes are part of the VPS trust boundary, as is the vault key itself.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from aiohttp import web


@dataclass(repr=False)
class LoginRequest:
    origin: str
    profile_home: str
    session_key: str
    actor: str
    owner_login: str
    is_current: Callable[[], bool]
    expires: float
    result: asyncio.Future = field(repr=False)
    kind: str = "login"
    label: str = ""
    cookie: str = field(default="", repr=False)
    csrf: str = field(default="", repr=False)


class SecureLoginService:
    """One gateway-loop-owned broker; request ownership never comes from HTTP input."""

    def __init__(self, base_url: str, port: int = 8874, ttl: int = 300):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".ts.net") or parsed.path not in ("", "/")
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Secure login requires a private Tailscale HTTPS origin")
        self.base_url = base_url.rstrip("/")
        self.host = parsed.netloc
        self.port = port
        self.ttl = min(max(ttl, 30), 300)
        self.pending: dict[str, LoginRequest] = {}
        self.runner: web.AppRunner | None = None
        self._start_lock = asyncio.Lock()

    async def start(self):
        async with self._start_lock:
            if self.runner is not None:
                return
            runner = web.AppRunner(self.application(), access_log=None)
            await runner.setup()
            try:
                await web.TCPSite(runner, "127.0.0.1", self.port).start()
            except Exception:
                await runner.cleanup()
                raise
            self.runner = runner

    async def close(self):
        for key in list(self.pending):
            self.cancel(key)
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    def create(self, *, origin, profile_home, session_key, actor, owner_login, is_current,
               kind="login", label="", ttl=None):
        parsed = urlsplit(origin)
        if kind not in ("login", "api_key", "token"):
            raise ValueError("Unsupported secure input kind")
        if kind != "login" and (not label.strip() or len(label) > 160):
            raise ValueError("Name the service for this key or token")
        if kind == "login" and (parsed.scheme not in ("http", "https") or not parsed.netloc
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Login must be bound to an exact website origin")
        if not all((profile_home, session_key, actor, owner_login)) or not is_current():
            raise ValueError("No live owner conversation")
        for key, entry in list(self.pending.items()):
            if not self.live(entry):
                self.cancel(key)
        if len(self.pending) >= 16:
            raise ValueError("Too many pending secure logins")
        token = secrets.token_urlsafe(32)
        lifetime = self.ttl if ttl is None else min(self.ttl, ttl)
        entry = LoginRequest(origin, profile_home, session_key, actor, owner_login,
                             is_current, time.monotonic() + lifetime,
                             asyncio.get_running_loop().create_future(), kind=kind, label=label)
        self.pending[token] = entry
        # Fragments are not sent in HTTP requests, referrers or link-preview GETs.
        return token, entry, self.base_url + "/#" + token

    @staticmethod
    def live(entry):
        return time.monotonic() < entry.expires and entry.is_current() and not entry.result.done()

    def cancel(self, token):
        entry = self.pending.pop(token, None)
        if entry is not None and not entry.result.done():
            entry.result.set_result(None)
        if entry is not None:
            entry.cookie = entry.csrf = ""

    def authenticate(self, request, *, mutate=False):
        if request.remote not in ("127.0.0.1", "::1") or request.host != self.host:
            raise web.HTTPForbidden(text="Private login unavailable")
        owner = request.headers.get("Tailscale-User-Login", "")
        if not owner:
            raise web.HTTPForbidden(text="Use your personal Tailscale connection")
        if mutate and request.headers.get("Origin") != self.base_url:
            raise web.HTTPForbidden(text="Reopen the secure link")
        return owner

    @web.middleware
    async def protect(self, request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.Response(status=exc.status, text=exc.text)
        except Exception:
            # Never echo exception details, request bodies or form values.
            response = web.Response(status=500, text="Secure login failed. Ask Zuri to retry.")
        response.headers.update({
            "Cache-Control": "no-store", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
        })
        return response

    def application(self):
        app = web.Application(client_max_size=16 * 1024, middlewares=[self.protect])
        app.router.add_get("/", self.page)
        app.router.add_get("/form.js", self.asset)
        app.router.add_get("/form.css", self.asset)
        app.router.add_post("/claim", self.claim)
        app.router.add_post("/save", self.save)
        app.router.add_post("/cancel", self.decline)
        return app

    async def page(self, request):
        self.authenticate(request)
        return web.Response(text=Path(__file__).with_name("secure_login_form.html").read_text(),
                            content_type="text/html")

    async def asset(self, request):
        self.authenticate(request)
        suffix = "js" if request.path == "/form.js" else "css"
        return web.Response(text=Path(__file__).with_name("secure_login_form." + suffix).read_text(),
                            content_type="application/javascript" if suffix == "js" else "text/css")

    async def claim(self, request):
        owner = self.authenticate(request, mutate=True)
        body = await request.json()
        token = body.get("token", "")
        if not isinstance(token, str):
            raise web.HTTPBadRequest(text="Invalid link")
        entry = self.pending.get(token)
        if entry is None or entry.owner_login != owner or not self.live(entry):
            raise web.HTTPGone(text="This link is not available. Ask Zuri for a new one.")
        entry.cookie = secrets.token_urlsafe(32)
        entry.csrf = secrets.token_urlsafe(32)
        response = web.json_response({"origin": entry.origin, "csrf": entry.csrf,
                                      "kind": entry.kind, "label": entry.label})
        response.set_cookie("__Host-zuri-login", entry.cookie, secure=True, httponly=True,
                            samesite="Strict", path="/", max_age=self.ttl)
        return response

    def claimed(self, request):
        owner = self.authenticate(request, mutate=True)
        cookie = request.cookies.get("__Host-zuri-login", "")
        csrf = request.headers.get("X-CSRF-Token", "")
        if not cookie or not csrf:
            raise web.HTTPForbidden(text="Reopen the secure link")
        for token, entry in self.pending.items():
            if (entry.cookie and secrets.compare_digest(entry.cookie, cookie)
                    and secrets.compare_digest(entry.csrf, csrf) and entry.owner_login == owner):
                if not self.live(entry):
                    raise web.HTTPGone(text="The task ended or the link expired")
                return token, entry
        raise web.HTTPForbidden(text="Reopen the secure link")

    async def save(self, request):
        token, entry = self.claimed(request)
        body = await request.json()
        identifier, password = body.get("identifier"), body.get("password")
        if (not isinstance(identifier, str) or not isinstance(password, str)
                or (entry.kind == "login" and not identifier.strip()) or not password
                or len(identifier) > 1024 or len(password) > 8192):
            raise web.HTTPBadRequest(text="Enter a login and password")
        # Reading the body yields: revalidate cancellation before releasing the waiter.
        self.claimed(request)
        self.pending.pop(token)
        entry.cookie = entry.csrf = ""
        entry.result.set_result({"identifier": identifier.strip(), "password": password,
                                 "_is_current": entry.is_current})
        body.clear()
        return web.json_response({"accepted": True})

    async def decline(self, request):
        token, _ = self.claimed(request)
        self.cancel(token)
        return web.json_response({"cancelled": True})
