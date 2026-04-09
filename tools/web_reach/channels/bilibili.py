"""Bilibili channel using the public search API and yt-dlp when available."""

from __future__ import annotations

import json
import shutil
import subprocess
from urllib.parse import quote, urlparse

import httpx

from ..utils import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT, strip_html
from .base import ChannelCheck, ReachChannel


def _run_ytdlp(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["yt-dlp", *args],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


class BilibiliChannel(ReachChannel):
    name = "bilibili"
    description = "Bilibili search and video metadata"
    search_prefixes = ("bilibili", "bili")

    def can_handle_url(self, url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return "bilibili.com" in netloc or "b23.tv" in netloc

    def check(self) -> ChannelCheck:
        if shutil.which("yt-dlp"):
            return ChannelCheck(status="ok", message="public search API + yt-dlp")
        return ChannelCheck(status="warn", message="search API available; yt-dlp unavailable for richer video extraction")

    def search(self, query: str, limit: int) -> list[dict[str, object]] | None:
        url = f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={quote(query)}&page=1"
        response = httpx.get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        items = (((payload.get("data") or {}).get("result")) or [])[:limit]
        results = []
        for idx, item in enumerate(items, start=1):
            results.append(
                {
                    "title": strip_html(item.get("title", "")),
                    "url": item.get("arcurl", ""),
                    "description": strip_html(item.get("description", "")[:280]),
                    "position": idx,
                }
            )
        return results

    async def extract(self, url: str, client) -> dict[str, object] | None:
        if not shutil.which("yt-dlp"):
            return None
        result = _run_ytdlp(["--dump-single-json", url])
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout or "{}")
        content = "\n".join(
            [
                f"# {payload.get('title', '')}",
                f"Uploader: {payload.get('uploader', '')}",
                f"Duration: {payload.get('duration_string') or payload.get('duration', '')}",
                f"Views: {payload.get('view_count', '')}",
                "",
                payload.get("description") or "",
            ]
        ).strip()
        return {
            "url": payload.get("webpage_url", url),
            "title": payload.get("title", ""),
            "content": content,
            "raw_content": content,
            "metadata": {
                "sourceURL": payload.get("webpage_url", url),
                "title": payload.get("title", ""),
                "backend": "reach",
                "channel": self.name,
            },
        }
