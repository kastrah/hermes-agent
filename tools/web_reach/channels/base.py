"""Base abstractions for no-API web-reach channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ChannelCheck:
    status: str
    message: str


class ReachChannel:
    """Base channel for URL-specific or prefix-specific web access."""

    name: str = ""
    description: str = ""
    search_prefixes: tuple[str, ...] = ()

    def can_handle_url(self, url: str) -> bool:
        return False

    def check(self) -> ChannelCheck:
        return ChannelCheck(status="ok", message="available")

    def search(self, query: str, limit: int) -> list[dict[str, Any]] | None:
        return None

    async def extract(self, url: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
        return None
