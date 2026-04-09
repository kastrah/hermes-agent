"""Generic public-web fallback channel."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from tools.website_policy import check_website_access

from ..utils import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    jina_reader_url,
    parse_jina_reader_response,
    resolve_duckduckgo_href,
    strip_html,
)
from .base import ChannelCheck, ReachChannel

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_RESULT_WITH_SNIPPET_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="(?P<href>.*?)">(?P<title>.*?)</a>'
    r'.*?<a class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.S,
)
_RESULT_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="(?P<href>.*?)">(?P<title>.*?)</a>',
    re.S,
)


def _build_result(url: str, title: str, description: str, position: int) -> dict[str, object]:
    return {
        "title": strip_html(title),
        "url": url,
        "description": strip_html(description),
        "position": position,
    }


def _host_allowed(url: str, allowed_hosts: tuple[str, ...] | None) -> bool:
    if not allowed_hosts:
        return True
    host = urlparse(url).netloc.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def _should_skip_result(url: str, allowed_hosts: tuple[str, ...] | None) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "duckduckgo.com" in host and parsed.path == "/y.js":
        return True
    return not _host_allowed(url, allowed_hosts)


def _parse_results(html_doc: str, limit: int, allowed_hosts: tuple[str, ...] | None = None) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen_urls = set()

    for match in _RESULT_WITH_SNIPPET_RE.finditer(html_doc):
        url = resolve_duckduckgo_href(match.group("href"))
        if not url or url in seen_urls or _should_skip_result(url, allowed_hosts):
            continue
        seen_urls.add(url)
        results.append(
            _build_result(
                url=url,
                title=match.group("title"),
                description=match.group("snippet"),
                position=len(results) + 1,
            )
        )
        if len(results) >= limit:
            return results

    for match in _RESULT_RE.finditer(html_doc):
        url = resolve_duckduckgo_href(match.group("href"))
        if not url or url in seen_urls or _should_skip_result(url, allowed_hosts):
            continue
        seen_urls.add(url)
        results.append(
            _build_result(
                url=url,
                title=match.group("title"),
                description="",
                position=len(results) + 1,
            )
        )
        if len(results) >= limit:
            break

    return results


class WebChannel(ReachChannel):
    name = "web"
    description = "Generic web search and page extraction"
    search_prefixes = ("web",)

    def check(self) -> ChannelCheck:
        return ChannelCheck(status="ok", message="DuckDuckGo HTML + Jina Reader")

    def search(
        self,
        query: str,
        limit: int,
        allowed_hosts: tuple[str, ...] | None = None,
    ) -> list[dict[str, object]]:
        response = httpx.get(
            _SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        return _parse_results(response.text, max(1, min(limit, 10)), allowed_hosts=allowed_hosts)

    async def extract(self, url: str, client: httpx.AsyncClient) -> dict[str, object]:
        blocked = check_website_access(url)
        if blocked:
            return {
                "url": url,
                "title": "",
                "content": "",
                "raw_content": "",
                "error": blocked["message"],
                "blocked_by_policy": {
                    "host": blocked["host"],
                    "rule": blocked["rule"],
                    "source": blocked["source"],
                },
            }

        response = await client.get(jina_reader_url(url))
        response.raise_for_status()
        title, source_url, content = parse_jina_reader_response(response.text, url)

        redirected_block = check_website_access(source_url)
        if redirected_block:
            return {
                "url": source_url,
                "title": title,
                "content": "",
                "raw_content": "",
                "error": redirected_block["message"],
                "blocked_by_policy": {
                    "host": redirected_block["host"],
                    "rule": redirected_block["rule"],
                    "source": redirected_block["source"],
                },
            }

        logger.info("No-API web fallback extracted %s", source_url)
        return {
            "url": source_url,
            "title": title,
            "content": content,
            "raw_content": content,
            "metadata": {
                "sourceURL": source_url,
                "title": title,
                "backend": "reach",
                "channel": self.name,
            },
        }
