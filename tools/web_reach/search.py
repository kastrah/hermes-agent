"""Channel-aware no-API web search."""

from __future__ import annotations

import json
import logging
import re

from .channels import get_channel_by_prefix
from .channels.web import WebChannel

logger = logging.getLogger(__name__)

_PREFIX_RE = re.compile(
    r"^(?P<prefix>reddit|github|gh|youtube|yt|bilibili|bili|v2ex|twitter|x|linkedin|web)\s*:\s*(?P<query>.+)$",
    re.I,
)


def no_api_web_search(query: str, limit: int = 5) -> str:
    """Search the public web without API keys, with optional channel prefixes."""
    query = (query or "").strip()
    limit = max(1, min(limit, 10))

    prefix_match = _PREFIX_RE.match(query)
    channel = None
    effective_query = query
    if prefix_match:
        channel = get_channel_by_prefix(prefix_match.group("prefix"))
        effective_query = prefix_match.group("query").strip()

    if channel is None:
        channel = WebChannel()

    try:
        results = channel.search(effective_query, limit)
    except Exception as exc:
        logger.debug("Channel search failed for %s: %s", channel.name, exc)
        results = None

    if results is None:
        fallback_query = effective_query
        if channel.name not in ("web",):
            fallback_query = f"site:{channel.name}.com {effective_query}" if channel.name != "github" else f"site:github.com {effective_query}"
        results = WebChannel().search(fallback_query, limit)

    logger.info("No-API web search channel=%s query=%s results=%d", channel.name, effective_query, len(results))
    return json.dumps({"success": True, "data": {"web": results}}, indent=2, ensure_ascii=False)
