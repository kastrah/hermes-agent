"""Shared helpers for Hermes's no-API web backend."""

from __future__ import annotations

import html
import re
from typing import Tuple
from urllib.parse import parse_qs, urlparse

import httpx


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; HermesAgent/1.0; +https://hermes-agent.nousresearch.com)"
)
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(value: str) -> str:
    """Convert small HTML fragments into normalized plain text."""
    plain = _TAG_RE.sub(" ", html.unescape(value or ""))
    return _WHITESPACE_RE.sub(" ", plain).strip()


def resolve_duckduckgo_href(href: str) -> str:
    """Resolve DuckDuckGo redirect links back to their target URL."""
    href = html.unescape(href or "").strip()
    if href.startswith("//"):
        href = f"https:{href}"

    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return target
    return href


def jina_reader_url(url: str) -> str:
    """Build the Jina Reader URL for a target page."""
    return f"https://r.jina.ai/{url}"


def parse_jina_reader_response(text: str, fallback_url: str) -> Tuple[str, str, str]:
    """Extract title/source metadata from a Jina Reader response."""
    title = ""
    source_url = fallback_url
    lines = text.splitlines()
    for line in lines[:12]:
        if line.startswith("Title: "):
            title = line.removeprefix("Title: ").strip()
        elif line.startswith("URL Source: "):
            source_url = line.removeprefix("URL Source: ").strip()
    return title, source_url, text.strip()
