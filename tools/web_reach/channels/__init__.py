"""Channel registry for Hermes no-API web reach."""

from __future__ import annotations

from .base import ChannelCheck, ReachChannel
from .bilibili import BilibiliChannel
from .github import GitHubChannel
from .linkedin import LinkedInChannel
from .reddit import RedditChannel
from .rss import RSSChannel
from .twitter import TwitterChannel
from .v2ex import V2EXChannel
from .web import WebChannel
from .youtube import YouTubeChannel

_CHANNELS: list[ReachChannel] = [
    TwitterChannel(),
    LinkedInChannel(),
    RedditChannel(),
    GitHubChannel(),
    YouTubeChannel(),
    BilibiliChannel(),
    RSSChannel(),
    V2EXChannel(),
    WebChannel(),
]


def all_channels() -> list[ReachChannel]:
    return list(_CHANNELS)


def get_channel_by_prefix(prefix: str) -> ReachChannel | None:
    lowered = prefix.lower().strip()
    for channel in _CHANNELS:
        if lowered in channel.search_prefixes:
            return channel
    return None


def detect_channel_for_url(url: str) -> ReachChannel:
    for channel in _CHANNELS:
        if channel.name == "web":
            continue
        if channel.can_handle_url(url):
            return channel
    return next(channel for channel in _CHANNELS if channel.name == "web")


def get_channel_diagnostics() -> list[dict[str, object]]:
    rows = []
    for channel in _CHANNELS:
        check = channel.check()
        rows.append(
            {
                "name": channel.name,
                "description": channel.description,
                "prefixes": list(channel.search_prefixes),
                "status": check.status,
                "message": check.message,
            }
        )
    return rows
