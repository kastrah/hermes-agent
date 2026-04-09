"""Reddit channel using the public JSON endpoints."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from ..utils import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT
from .base import ChannelCheck, ReachChannel

_HEADERS = {"User-Agent": "hermes-agent/1.0"}


def _listing_to_search_results(payload: dict, limit: int) -> list[dict[str, object]]:
    results = []
    for idx, child in enumerate(payload.get("data", {}).get("children", [])[:limit], start=1):
        data = child.get("data", {})
        permalink = data.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else data.get("url", "")
        results.append(
            {
                "title": data.get("title", ""),
                "url": url,
                "description": (data.get("selftext") or data.get("subreddit_name_prefixed") or "")[:280],
                "position": idx,
            }
        )
    return results


def _render_post(payload: list[dict]) -> tuple[str, str]:
    post_listing = payload[0] if payload else {}
    comments_listing = payload[1] if len(payload) > 1 else {}
    children = post_listing.get("data", {}).get("children", [])
    if not children:
        return "", "No Reddit post data found."

    data = children[0].get("data", {})
    title = data.get("title", "")
    lines = [
        f"# {title}",
        f"Subreddit: r/{data.get('subreddit', '')}",
        f"Author: u/{data.get('author', '')}",
        f"Score: {data.get('score', 0)}",
        "",
        data.get("selftext") or data.get("url_overridden_by_dest") or "",
        "",
        "## Top Comments",
    ]
    for child in comments_listing.get("data", {}).get("children", [])[:10]:
        comment = child.get("data", {})
        body = comment.get("body")
        if not body:
            continue
        lines.extend(
            [
                f"- u/{comment.get('author', '')} ({comment.get('score', 0)} points)",
                body,
            ]
        )
    return title, "\n".join(line for line in lines if line is not None).strip()


class RedditChannel(ReachChannel):
    name = "reddit"
    description = "Reddit posts, search, and subreddit listings"
    search_prefixes = ("reddit",)

    def can_handle_url(self, url: str) -> bool:
        netloc = urlparse(url).netloc.lower()
        return "reddit.com" in netloc or "redd.it" in netloc

    def check(self) -> ChannelCheck:
        try:
            response = httpx.get(
                "https://www.reddit.com/r/python/hot.json?limit=1",
                headers=_HEADERS,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()
            return ChannelCheck(status="ok", message="public JSON endpoints available")
        except Exception as exc:
            return ChannelCheck(status="warn", message=f"Reddit JSON may be blocked: {exc}")

    def search(self, query: str, limit: int) -> list[dict[str, object]]:
        response = httpx.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "limit": min(limit, 10)},
            headers=_HEADERS,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        return _listing_to_search_results(response.json(), limit)

    async def extract(self, url: str, client: httpx.AsyncClient) -> dict[str, object] | None:
        parsed = urlparse(url)
        resolved_url = url
        if "redd.it" in parsed.netloc.lower():
            response = await client.get(url)
            response.raise_for_status()
            resolved_url = str(response.url)
            parsed = urlparse(resolved_url)

        if not parsed.path:
            return None

        if "/comments/" in parsed.path:
            response = await client.get(f"https://www.reddit.com{parsed.path.rstrip('/')}.json", headers=_HEADERS)
            response.raise_for_status()
            payload = response.json()
            title, content = _render_post(payload)
            return {
                "url": resolved_url,
                "title": title,
                "content": content,
                "raw_content": content,
                "metadata": {
                    "sourceURL": resolved_url,
                    "title": title,
                    "backend": "reach",
                    "channel": self.name,
                },
            }

        if parsed.path.startswith("/search"):
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            results = self.search(query, 10)
            content = "\n".join(f"- {r['title']} — {r['url']}" for r in results)
            return {
                "url": resolved_url,
                "title": f"Reddit search: {query}",
                "content": content,
                "raw_content": content,
                "metadata": {
                    "sourceURL": resolved_url,
                    "title": f"Reddit search: {query}",
                    "backend": "reach",
                    "channel": self.name,
                },
            }

        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "r":
            subreddit = segments[1]
            response = await client.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json",
                params={"limit": 10},
                headers=_HEADERS,
            )
            response.raise_for_status()
            results = _listing_to_search_results(response.json(), 10)
            content = "\n".join(f"- {r['title']} — {r['url']}" for r in results)
            return {
                "url": resolved_url,
                "title": f"r/{subreddit}",
                "content": content,
                "raw_content": content,
                "metadata": {
                    "sourceURL": resolved_url,
                    "title": f"r/{subreddit}",
                    "backend": "reach",
                    "channel": self.name,
                },
            }

        return None
