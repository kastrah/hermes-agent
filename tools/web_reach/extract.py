"""Channel-aware no-API extraction."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .channels import detect_channel_for_url
from .channels.web import WebChannel
from .utils import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


async def _extract_single_url(client: httpx.AsyncClient, url: str) -> dict[str, object]:
    channel = detect_channel_for_url(url)
    try:
        result = await channel.extract(url, client)
        if result is None and channel.name != "web":
            result = await WebChannel().extract(url, client)
        if result is None:
            raise ValueError(f"No extractor available for {url}")
        logger.info("No-API extract channel=%s url=%s", channel.name, url)
        return result
    except Exception as exc:
        logger.debug("No-API extract failed for %s: %s", url, exc)
        return {
            "url": url,
            "title": "",
            "content": "",
            "raw_content": "",
            "error": str(exc),
        }


async def no_api_web_extract(urls: list[str]) -> list[dict[str, object]]:
    """Extract URLs without API keys, using channel-specific handlers when possible."""
    async with httpx.AsyncClient(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        tasks = [_extract_single_url(client, url) for url in urls]
        return await asyncio.gather(*tasks)
