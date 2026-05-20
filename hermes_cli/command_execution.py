# hermes_cli/command_execution.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    continue_running: bool = True
    message: str | None = None
    fallthrough_to_agent: bool = False

    @classmethod
    def handled(cls, message: str | None = None) -> "CommandResult":
        return cls(message=message)

    @classmethod
    def exit(cls) -> "CommandResult":
        return cls(continue_running=False)

    @classmethod
    def fallthrough(cls, message: str | None = None) -> "CommandResult":
        return cls(message=message, fallthrough_to_agent=True)


@dataclass(frozen=True)
class CommandPayload:
    payload: str
    has_payload: bool


def command_payload(raw_command: str) -> CommandPayload:
    parts = raw_command.split(None, 1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    return CommandPayload(payload=payload, has_payload=bool(payload))


def queue_status(payload: str, agent_running: bool) -> str:
    preview = payload[:80] + ("..." if len(payload) > 80 else "")
    if agent_running:
        return f"Queued for the next turn: {preview}"
    return f"Queued: {preview}"


def steer_status(payload: str, accepted: bool | None) -> str:
    preview = payload[:80] + ("..." if len(payload) > 80 else "")
    if accepted is True:
        return f"⏩ Steer queued — arrives after the next tool call: {preview}"
    if accepted is False:
        return "Steer rejected (empty payload)."
    return f"No agent running; queued as next turn: {preview}"


def quick_command_target(raw_command: str, base_command: str, qcmd: dict) -> str | None:
    target = str(qcmd.get("target", "")).strip()
    if not target:
        return None
    target = target if target.startswith("/") else f"/{target}"
    user_args = raw_command[len(base_command):].strip()
    return f"{target} {user_args}".strip()


@dataclass(frozen=True)
class QuickCommandResolution:
    rewritten_command: str | None = None
    exec_command: str | None = None
    error: str | None = None


def resolve_quick_command(raw_command: str, base_command: str, quick_commands: dict) -> QuickCommandResolution | None:
    key = base_command.lstrip("/")
    qcmd = quick_commands.get(key)
    if not qcmd:
        return None
    if qcmd.get("type") == "alias":
        target = quick_command_target(raw_command, base_command, qcmd)
        if not target:
            return QuickCommandResolution(error=f"Quick command '{base_command}' has no target defined")
        return QuickCommandResolution(rewritten_command=target)
    if qcmd.get("type") == "exec":
        command = str(qcmd.get("command", "")).strip()
        if not command:
            return QuickCommandResolution(error=f"Quick command '{base_command}' has no command defined")
        return QuickCommandResolution(exec_command=command)
    return QuickCommandResolution(error=f"Unsupported type for quick command '{base_command}'")
