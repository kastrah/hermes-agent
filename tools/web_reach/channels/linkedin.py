"""LinkedIn channel with public fallback and optional MCP-aware diagnostics."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from urllib.parse import urlparse

from .base import ChannelCheck, ReachChannel
from .web import WebChannel

_LINKEDIN_COOKIE_ENV_VARS = ("LINKEDIN_LI_AT", "LINKEDIN_JSESSIONID")


def _linkedin_cookie_env_present() -> bool:
    return all(os.environ.get(key) for key in _LINKEDIN_COOKIE_ENV_VARS)


def _linkedin_browser_cookie_values() -> tuple[str, str] | None:
    if importlib.util.find_spec("browser_cookie3") is None:
        return None

    try:
        import browser_cookie3
    except Exception:
        return None

    for domain_name in (".linkedin.com", "www.linkedin.com", "linkedin.com"):
        try:
            jar = browser_cookie3.chrome(domain_name=domain_name)
        except Exception:
            continue

        li_at = None
        jsessionid = None
        for cookie in jar:
            if cookie.name == "li_at":
                li_at = cookie.value
            elif cookie.name == "JSESSIONID":
                jsessionid = cookie.value
        if li_at and jsessionid:
            return li_at, jsessionid
    return None


def _linkedin_cookie_source() -> tuple[str, str, str] | None:
    if _linkedin_cookie_env_present():
        return "env", os.environ["LINKEDIN_LI_AT"], os.environ["LINKEDIN_JSESSIONID"]

    browser_cookies = _linkedin_browser_cookie_values()
    if browser_cookies:
        li_at, jsessionid = browser_cookies
        return "chrome", li_at, jsessionid

    return None


def _linkedin_api_available() -> bool:
    return importlib.util.find_spec("linkedin_api") is not None


def _linkedin_cookie_ready() -> bool:
    return _linkedin_cookie_source() is not None and _linkedin_api_available()


def _linkedin_cookie_client():
    cookie_source = _linkedin_cookie_source()
    if cookie_source is None or not _linkedin_api_available():
        return None

    try:
        from linkedin_api import Linkedin
        from requests.cookies import RequestsCookieJar

        _, li_at, jsessionid = cookie_source
        jar = RequestsCookieJar()
        jar.set("li_at", li_at, domain=".www.linkedin.com")
        jar.set("JSESSIONID", jsessionid, domain=".www.linkedin.com")
        return Linkedin("", "", cookies=jar)
    except Exception:
        return None


def _linkedin_public_id(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "in":
        return parts[1]
    return None


def _clean_linkedin_url(url: str) -> str:
    if not url:
        return url
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _mcporter_path() -> str | None:
    return shutil.which("mcporter")


def _run_mcporter(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    mcporter = _mcporter_path()
    if not mcporter:
        return None
    try:
        return subprocess.run(
            [mcporter, *args],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception:
        return None


def _linkedin_configured() -> bool:
    result = _run_mcporter(["config", "list"])
    return bool(result and "linkedin" in (result.stdout or "").lower())


def _parse_mcporter_json(text: str):
    try:
        return json.loads((text or "").strip())
    except Exception:
        return None


def _render_json_payload(payload, fallback_title: str) -> tuple[str, str]:
    if isinstance(payload, dict):
        title = (
            payload.get("name")
            or payload.get("fullName")
            or payload.get("headline")
            or payload.get("title")
            or fallback_title
        )
    else:
        title = fallback_title
    return title, json.dumps(payload, indent=2, ensure_ascii=False)


class LinkedInChannel(ReachChannel):
    name = "linkedin"
    description = "LinkedIn profiles and posts"
    search_prefixes = ("linkedin",)

    def can_handle_url(self, url: str) -> bool:
        return "linkedin.com" in urlparse(url).netloc.lower()

    def check(self) -> ChannelCheck:
        cookie_source = _linkedin_cookie_source()
        if cookie_source is not None and _linkedin_api_available():
            source_name = "Chrome cookies" if cookie_source[0] == "chrome" else "LINKEDIN_LI_AT/JSESSIONID"
            return ChannelCheck(
                status="ok",
                message=f"LinkedIn cookie adapter configured via {source_name}",
            )
        if cookie_source is not None and not _linkedin_api_available():
            return ChannelCheck(
                status="warn",
                message="LinkedIn cookies found, but python package `linkedin_api` is not installed",
            )
        mcporter = _mcporter_path()
        if not mcporter:
            return ChannelCheck(
                status="warn",
                message="public read fallback available; add LinkedIn cookies or configure mcporter for richer LinkedIn access",
            )
        try:
            if _linkedin_configured():
                return ChannelCheck(status="ok", message="mcporter LinkedIn connector configured")
        except Exception:
            pass
        return ChannelCheck(
            status="warn",
            message="public read fallback available; mcporter present but LinkedIn connector not configured, and no LinkedIn cookie adapter found",
        )

    def search(self, query: str, limit: int) -> list[dict[str, object]]:
        cookie_client = _linkedin_cookie_client()
        if cookie_client is not None:
            try:
                payload = cookie_client.search(
                    {
                        "filters": "List((key:resultType,value:List(PEOPLE)))",
                        "keywords": query,
                    },
                    limit=min(limit, 10),
                )
            except Exception:
                payload = None
            if isinstance(payload, list):
                results = []
                for idx, item in enumerate(payload[:limit], start=1):
                    if not isinstance(item, dict):
                        continue
                    public_id = item.get("public_id") or item.get("publicIdentifier") or ""
                    url = (
                        item.get("navigationUrl")
                        or item.get("linkedin_url")
                        or item.get("url")
                        or item.get("profileUrl")
                        or ""
                    )
                    if not url and public_id:
                        url = f"https://www.linkedin.com/in/{public_id}"
                    title = (
                        item.get("name")
                        or item.get("fullName")
                        or ((item.get("title") or {}).get("text") if isinstance(item.get("title"), dict) else None)
                        or f"LinkedIn result {idx}"
                    )
                    description = (
                        item.get("headline")
                        or item.get("jobtitle")
                        or item.get("summary")
                        or ((item.get("primarySubtitle") or {}).get("text") if isinstance(item.get("primarySubtitle"), dict) else None)
                        or ""
                    )
                    results.append(
                        {
                            "title": title,
                            "url": _clean_linkedin_url(url),
                            "description": description[:280],
                            "position": idx,
                        }
                    )
                if results:
                    return results

        if _linkedin_configured():
            result = _run_mcporter(
                ["call", f'linkedin.search_people(keyword: "{query}", limit: {min(limit, 10)})']
            )
            if result and result.returncode == 0:
                payload = _parse_mcporter_json(result.stdout)
                if isinstance(payload, list):
                    results = []
                    for idx, item in enumerate(payload[:limit], start=1):
                        if not isinstance(item, dict):
                            continue
                        url = item.get("linkedin_url") or item.get("url") or item.get("profileUrl") or ""
                        title = item.get("name") or item.get("fullName") or item.get("headline") or f"LinkedIn result {idx}"
                        description = item.get("headline") or item.get("summary") or ""
                        results.append(
                            {
                                "title": title,
                                "url": url,
                                "description": description[:280],
                                "position": idx,
                            }
                        )
                    if results:
                        return results
        return WebChannel().search(f"site:linkedin.com {query}", limit)

    async def extract(self, url: str, client) -> dict[str, object] | None:
        public_id = _linkedin_public_id(url)
        cookie_client = _linkedin_cookie_client()
        if cookie_client is not None and public_id:
            try:
                payload = cookie_client.get_profile(public_id)
            except Exception:
                payload = None
            if payload is not None:
                title, content = _render_json_payload(payload, "LinkedIn Profile")
                return {
                    "url": url,
                    "title": title,
                    "content": content,
                    "raw_content": content,
                    "metadata": {
                        "sourceURL": url,
                        "title": title,
                        "backend": "reach",
                        "channel": self.name,
                        "adapter": "linkedin-cookies",
                    },
                }

        if _linkedin_configured() and "/in/" in urlparse(url).path:
            result = _run_mcporter(
                ["call", f'linkedin.get_person_profile(linkedin_url: "{url}")']
            )
            if result and result.returncode == 0:
                payload = _parse_mcporter_json(result.stdout)
                if payload is not None:
                    title, content = _render_json_payload(payload, "LinkedIn Profile")
                    return {
                        "url": url,
                        "title": title,
                        "content": content,
                        "raw_content": content,
                        "metadata": {
                            "sourceURL": url,
                            "title": title,
                            "backend": "reach",
                            "channel": self.name,
                            "adapter": "mcporter",
                        },
                    }

        result = await WebChannel().extract(url, client)
        metadata = dict(result.get("metadata", {}))
        metadata["channel"] = self.name
        result["metadata"] = metadata
        return result
