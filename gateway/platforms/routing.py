"""Shared platform routing decisions.

Adapters should translate platform-native messages into these facts, then ask
this Module whether a message should enter Hermes.  That keeps policy local and
makes platform-specific code mostly about translation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingFacts:
    is_dm: bool = False
    allowed_chat: bool = True
    ignored_thread: bool = False
    free_response: bool = False
    require_mention: bool = True
    authored_by_bot: bool = False
    mentions_self: bool = False
    mentions_other: bool = False
    contains_other_handle: bool = False
    replies_to_self: bool = False
    replies_to_other_bot: bool = False
    matches_wake_pattern: bool = False
    command_targets_self: bool = True


@dataclass(frozen=True)
class RoutingDecision:
    should_process: bool
    reason: str

    @classmethod
    def allow(cls, reason: str) -> "RoutingDecision":
        return cls(True, reason)

    @classmethod
    def drop(cls, reason: str) -> "RoutingDecision":
        return cls(False, reason)


def decide_message_routing(facts: RoutingFacts) -> RoutingDecision:
    """Return the platform-independent routing decision for one message."""
    if facts.is_dm:
        return RoutingDecision.allow("dm")
    if not facts.allowed_chat:
        return RoutingDecision.drop("chat_not_allowed")
    if facts.ignored_thread:
        return RoutingDecision.drop("thread_ignored")
    if not facts.command_targets_self:
        return RoutingDecision.drop("command_targets_other_bot")
    if facts.authored_by_bot:
        return RoutingDecision.drop("authored_by_bot")
    if facts.free_response:
        return RoutingDecision.allow("free_response")
    if not facts.require_mention:
        return RoutingDecision.allow("mention_not_required")
    if facts.mentions_self:
        return RoutingDecision.allow("mentions_self")
    if facts.mentions_other:
        return RoutingDecision.drop("mentions_other")
    if facts.contains_other_handle:
        return RoutingDecision.drop("contains_other_handle")
    if facts.replies_to_other_bot:
        return RoutingDecision.drop("replies_to_other_bot")
    if facts.replies_to_self:
        return RoutingDecision.allow("replies_to_self")
    if facts.matches_wake_pattern:
        return RoutingDecision.allow("wake_pattern")
    return RoutingDecision.drop("mention_required")


def channel_set(raw) -> set[str]:
    """Normalize scalar/list/CSV channel config into a string set."""
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(part).strip() for part in raw if str(part).strip()}
    text = str(raw).strip()
    if not text:
        return set()
    return {part.strip() for part in text.split(",") if part.strip()}
