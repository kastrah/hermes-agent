"""RSS/Atom channel."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from urllib.parse import urlparse

from .base import ChannelCheck, ReachChannel


def _find_text(node: ET.Element, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


class RSSChannel(ReachChannel):
    name = "rss"
    description = "RSS and Atom feeds"

    def can_handle_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(fragment in lowered for fragment in ("/feed", "/rss", ".xml", "atom"))

    def check(self) -> ChannelCheck:
        return ChannelCheck(status="ok", message="xml.etree-based RSS/Atom parsing")

    async def extract(self, url: str, client) -> dict[str, object] | None:
        response = await client.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        channel = root.find("channel")
        if channel is not None:
            title = _find_text(channel, "title") or urlparse(url).netloc
            items = channel.findall("item")[:10]
            lines = [f"# {title}", ""]
            for item in items:
                item_title = _find_text(item, "title")
                item_link = _find_text(item, "link")
                item_desc = _find_text(item, "description")
                lines.extend([f"- {item_title}", item_link, item_desc, ""])
        else:
            title = _find_text(root, "{http://www.w3.org/2005/Atom}title") or urlparse(url).netloc
            items = root.findall("{http://www.w3.org/2005/Atom}entry")[:10]
            lines = [f"# {title}", ""]
            for item in items:
                item_title = _find_text(item, "{http://www.w3.org/2005/Atom}title")
                link_node = item.find("{http://www.w3.org/2005/Atom}link")
                item_link = link_node.attrib.get("href", "") if link_node is not None else ""
                item_summary = _find_text(item, "{http://www.w3.org/2005/Atom}summary")
                lines.extend([f"- {item_title}", item_link, item_summary, ""])

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
