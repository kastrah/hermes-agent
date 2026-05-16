"""State owner for gateway session runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass
class GatewayRuntimeState:
    running_agents: dict[str, Any] = field(default_factory=dict)
    running_started_at: dict[str, float] = field(default_factory=dict)
    busy_ack_at: dict[str, float] = field(default_factory=dict)
    run_generation: dict[str, int] = field(default_factory=dict)

    def claim_pending(self, session_key: str, pending_sentinel: Any) -> int:
        if not session_key:
            return 0
        self.running_agents[session_key] = pending_sentinel
        self.running_started_at[session_key] = time()
        return self.begin_generation(session_key)

    def bind_agent(self, session_key: str, agent: Any, generation: int | None = None) -> bool:
        if not session_key:
            return False
        if generation is not None and not self.is_current(session_key, generation):
            return False
        self.running_agents[session_key] = agent
        self.running_started_at.setdefault(session_key, time())
        return True

    def release(self, session_key: str, generation: int | None = None) -> bool:
        if not session_key:
            return False
        if generation is not None and not self.is_current(session_key, generation):
            return False
        self.running_agents.pop(session_key, None)
        self.running_started_at.pop(session_key, None)
        self.busy_ack_at.pop(session_key, None)
        return True

    def begin_generation(self, session_key: str) -> int:
        if not session_key:
            return 0
        next_generation = int(self.run_generation.get(session_key, 0)) + 1
        self.run_generation[session_key] = next_generation
        return next_generation

    def is_current(self, session_key: str, generation: int) -> bool:
        if not session_key:
            return True
        return int(self.run_generation.get(session_key, 0)) == int(generation)
