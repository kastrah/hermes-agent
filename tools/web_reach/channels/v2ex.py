"""V2EX channel using the public API."""

from __future__ import annotations

import httpx
from urllib.parse import urlparse

from ..utils import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT
from .base import ChannelCheck, ReachChannel


class V2EXChannel(ReachChannel):
    name = "v2ex"
    description = "V2EX topics and member profiles"
    search_prefixes = ("v2ex",)

    def can_handle_url(self, url: str) -> bool:
        return "v2ex.com" in urlparse(url).netloc.lower()

    def check(self) -> ChannelCheck:
        try:
            response = httpx.get(
                "https://www.v2ex.com/api/topics/hot.json",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return ChannelCheck(status="ok", message="public V2EX API available")
        except Exception as exc:
            return ChannelCheck(status="warn", message=f"V2EX API failed: {exc}")

    async def extract(self, url: str, client) -> dict[str, object] | None:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "t":
            topic_id = parts[1]
            topic_response = await client.get(
                "https://www.v2ex.com/api/topics/show.json",
                params={"id": topic_id},
            )
            replies_response = await client.get(
                "https://www.v2ex.com/api/replies/show.json",
                params={"topic_id": topic_id, "page": 1},
            )
            topic_response.raise_for_status()
            replies_response.raise_for_status()
            topic_list = topic_response.json() or []
            topic = topic_list[0] if topic_list else {}
            replies = replies_response.json() or []
            title = topic.get("title", "")
            lines = [f"# {title}", "", topic.get("content", ""), "", "## Replies"]
            for reply in replies[:10]:
                member = reply.get("member") or {}
                lines.extend([f"- {member.get('username', '')}", reply.get("content", "")])
            content = "\n".join(lines).strip()
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
                },
            }

        if len(parts) >= 2 and parts[0] == "member":
            username = parts[1]
            response = await client.get(
                "https://www.v2ex.com/api/members/show.json",
                params={"username": username},
            )
            response.raise_for_status()
            member = response.json() or {}
            content = "\n".join(
                [
                    f"# {member.get('username', username)}",
                    member.get("bio", ""),
                    "",
                    f"GitHub: {member.get('github', '')}",
                    f"Website: {member.get('website', '')}",
                    f"Location: {member.get('location', '')}",
                ]
            ).strip()
            return {
                "url": url,
                "title": member.get("username", username),
                "content": content,
                "raw_content": content,
                "metadata": {
                    "sourceURL": url,
                    "title": member.get("username", username),
                    "backend": "reach",
                    "channel": self.name,
                },
            }

        return None
