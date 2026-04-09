"""Twitter/X channel with robust public fallbacks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from urllib.parse import urlparse

from .base import ChannelCheck, ReachChannel
from .web import WebChannel

_URL_RE = re.compile(r"https?://(?:x|twitter)\.com/\S+")


def _bird_path() -> str | None:
    return shutil.which("bird") or shutil.which("birdx")


def _run_bird(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    bird = _bird_path()
    if not bird:
        return None
    try:
        return subprocess.run(
            [bird, *args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return None


def _bird_ready() -> bool:
    result = _run_bird(["check"])
    return bool(result and result.returncode == 0)


def _extract_title_and_content(text: str, fallback_title: str) -> tuple[str, str]:
    stripped = (text or "").strip()
    if not stripped:
        return fallback_title, stripped
    first_line = next((line.strip() for line in stripped.splitlines() if line.strip()), fallback_title)
    return first_line[:160], stripped


def _parse_bird_search_output(text: str, limit: int) -> list[dict[str, object]]:
    stripped = (text or "").strip()
    if not stripped:
        return []

    try:
        payload = json.loads(stripped)
    except Exception:
        payload = None

    if isinstance(payload, list):
        results = []
        for idx, item in enumerate(payload[:limit], start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("tweet_url") or ""
            text_value = item.get("text") or item.get("full_text") or item.get("content") or ""
            author = item.get("author") or item.get("username") or ""
            title = f"{author}: {text_value[:100]}".strip(": ")
            results.append(
                {
                    "title": title or url or f"X/Twitter result {idx}",
                    "url": url,
                    "description": text_value[:280],
                    "position": idx,
                }
            )
        return results

    results = []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", stripped) if block.strip()]
    for block in blocks:
        url_match = _URL_RE.search(block)
        if not url_match:
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        title = next((line for line in lines if not _URL_RE.search(line)), url_match.group(0))
        results.append(
            {
                "title": title[:160],
                "url": url_match.group(0),
                "description": " ".join(lines)[:280],
                "position": len(results) + 1,
            }
        )
        if len(results) >= limit:
            break
    return results


class TwitterChannel(ReachChannel):
    name = "twitter"
    description = "X/Twitter posts and articles"
    search_prefixes = ("twitter", "x")

    def can_handle_url(self, url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return "x.com" in netloc or "twitter.com" in netloc

    def check(self) -> ChannelCheck:
        bird = _bird_path()
        if not bird:
            return ChannelCheck(
                status="warn",
                message=(
                    "public read fallback available; richer X/Twitter access needs jawond/bird "
                    "(git clone https://github.com/jawond/bird.git && pnpm install && pnpm run build && npm link)"
                ),
            )
        try:
            result = _run_bird(["check"])
            if result.returncode == 0:
                return ChannelCheck(status="ok", message="bird CLI available")
        except Exception:
            pass
        return ChannelCheck(
            status="warn",
            message=(
                "public read fallback available; bird is installed but not ready "
                "(run `bird whoami` or `bird check` and set cookies/auth as needed)"
            ),
        )

    def search(self, query: str, limit: int) -> list[dict[str, object]]:
        if _bird_ready():
            result = _run_bird(["search", query, "-n", str(min(limit, 10))])
            if result and result.returncode == 0:
                parsed = _parse_bird_search_output(result.stdout, limit)
                if parsed:
                    return parsed
        fallback = f"(site:x.com OR site:twitter.com) {query}"
        return WebChannel().search(fallback, limit)

    async def extract(self, url: str, client) -> dict[str, object] | None:
        if _bird_ready():
            command = ["thread", url] if "/status/" in urlparse(url).path else ["read", url]
            result = _run_bird(command)
            if result and result.returncode == 0 and (result.stdout or "").strip():
                title, content = _extract_title_and_content(result.stdout, "X/Twitter")
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
                        "adapter": "bird",
                    },
                }

        result = await WebChannel().extract(url, client)
        metadata = dict(result.get("metadata", {}))
        metadata["channel"] = self.name
        result["metadata"] = metadata
        return result
