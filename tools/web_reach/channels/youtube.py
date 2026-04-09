"""YouTube channel powered by yt-dlp when installed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from .base import ChannelCheck, ReachChannel
from .web import WebChannel


def _run_ytdlp(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["yt-dlp", *args],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


def _clean_vtt(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "WEBVTT" or stripped.isdigit() or "-->" in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


class YouTubeChannel(ReachChannel):
    name = "youtube"
    description = "YouTube video metadata and captions"
    search_prefixes = ("youtube", "yt")

    def can_handle_url(self, url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return "youtube.com" in netloc or "youtu.be" in netloc

    def check(self) -> ChannelCheck:
        if not shutil.which("yt-dlp"):
            return ChannelCheck(status="warn", message="yt-dlp unavailable; will fall back to generic web reads")
        return ChannelCheck(status="ok", message="yt-dlp available")

    def search(self, query: str, limit: int) -> list[dict[str, object]] | None:
        if not shutil.which("yt-dlp"):
            return WebChannel().search(
                f"site:youtube.com {query}",
                limit,
                allowed_hosts=("youtube.com", "youtu.be"),
            )

        try:
            result = _run_ytdlp(["--dump-single-json", f"ytsearch{min(limit, 10)}:{query}"])
        except subprocess.TimeoutExpired:
            result = None

        if result and result.returncode == 0:
            payload = json.loads(result.stdout or "{}")
            entries = payload.get("entries") or []
            results = []
            for idx, entry in enumerate(entries[:limit], start=1):
                results.append(
                    {
                        "title": entry.get("title", ""),
                        "url": entry.get("webpage_url") or entry.get("url", ""),
                        "description": entry.get("description", "")[:280],
                        "position": idx,
                    }
                )
            if results:
                return results

        return WebChannel().search(
            f"site:youtube.com {query}",
            limit,
            allowed_hosts=("youtube.com", "youtu.be"),
        )

    async def extract(self, url: str, client) -> dict[str, object] | None:
        if not shutil.which("yt-dlp"):
            return None
        try:
            result = _run_ytdlp(["--dump-single-json", url])
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout or "{}")

        transcript = ""
        with tempfile.TemporaryDirectory(prefix="hermes-youtube-") as tempdir:
            subtitle_result = _run_ytdlp(
                [
                    "--skip-download",
                    "--write-sub",
                    "--write-auto-sub",
                    "--sub-format",
                    "vtt",
                    "--sub-langs",
                    "en.*,en",
                    "-o",
                    os.path.join(tempdir, "%(id)s.%(ext)s"),
                    url,
                ]
            )
            if subtitle_result.returncode == 0:
                vtt_files = [
                    os.path.join(tempdir, name)
                    for name in os.listdir(tempdir)
                    if name.endswith(".vtt")
                ]
                if vtt_files:
                    with open(vtt_files[0], "r", encoding="utf-8", errors="ignore") as handle:
                        transcript = _clean_vtt(handle.read())

        lines = [
            f"# {payload.get('title', '')}",
            f"Uploader: {payload.get('uploader', '')}",
            f"Duration: {payload.get('duration_string') or payload.get('duration', '')}",
            f"Views: {payload.get('view_count', '')}",
            "",
            payload.get("description") or "",
        ]
        if transcript:
            lines.extend(["", "## Transcript", transcript[:12000]])
        content = "\n".join(lines).strip()
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
