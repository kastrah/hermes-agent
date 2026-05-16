"""Tool schema assembly behind a single deep Module."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from tools.tool_policy import resolve_tool_names

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSchemaResult:
    definitions: list[dict[str, Any]]
    resolved_tool_names: list[str]


def assemble_tool_definitions(
    *,
    enabled_toolsets=None,
    disabled_toolsets=None,
    quiet_mode: bool = False,
    registry,
) -> ToolSchemaResult:
    plan = resolve_tool_names(enabled_toolsets, disabled_toolsets, quiet_mode, registry)
    filtered_tools = registry.get_definitions(plan.tool_names, quiet=quiet_mode)
    available_tool_names = {t["function"]["name"] for t in filtered_tools}

    filtered_tools = _apply_execute_code_schema(filtered_tools, available_tool_names)
    filtered_tools, available_tool_names = _apply_discord_schemas(filtered_tools, available_tool_names)
    filtered_tools = _strip_missing_web_tool_references(filtered_tools, available_tool_names)

    if not quiet_mode:
        if filtered_tools:
            tool_names = [t["function"]["name"] for t in filtered_tools]
            print(f"🛠️  Final tool selection ({len(filtered_tools)} tools): {', '.join(tool_names)}")
        else:
            print("🛠️  No tools selected (all filtered out or unavailable)")

    try:
        from tools.schema_sanitizer import sanitize_tool_schemas
        filtered_tools = sanitize_tool_schemas(filtered_tools)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Schema sanitization skipped: %s", e)

    return ToolSchemaResult(
        definitions=filtered_tools,
        resolved_tool_names=[t["function"]["name"] for t in filtered_tools],
    )


def _apply_execute_code_schema(filtered_tools, available_tool_names):
    if "execute_code" not in available_tool_names:
        return filtered_tools
    from tools.code_execution_tool import SANDBOX_ALLOWED_TOOLS, build_execute_code_schema, _get_execution_mode

    sandbox_enabled = SANDBOX_ALLOWED_TOOLS & available_tool_names
    dynamic_schema = build_execute_code_schema(sandbox_enabled, mode=_get_execution_mode())
    return _replace_tool_schema(filtered_tools, "execute_code", dynamic_schema)


def _apply_discord_schemas(filtered_tools, available_tool_names):
    schema_fns = {
        "discord": "get_dynamic_schema_core",
        "discord_admin": "get_dynamic_schema_admin",
    }
    for tool_name, fn_name in schema_fns.items():
        if tool_name not in available_tool_names:
            continue
        try:
            from tools import discord_tool as discord_tool
            dynamic = getattr(discord_tool, fn_name)()
        except Exception:
            dynamic = None
        if dynamic is None:
            filtered_tools = [
                tool for tool in filtered_tools
                if tool.get("function", {}).get("name") != tool_name
            ]
            available_tool_names.discard(tool_name)
        else:
            filtered_tools = _replace_tool_schema(filtered_tools, tool_name, dynamic)
    return filtered_tools, available_tool_names


def _strip_missing_web_tool_references(filtered_tools, available_tool_names):
    if "browser_navigate" not in available_tool_names:
        return filtered_tools
    if {"web_search", "web_extract"} & available_tool_names:
        return filtered_tools
    for i, tool in enumerate(filtered_tools):
        if tool.get("function", {}).get("name") == "browser_navigate":
            desc = tool["function"].get("description", "")
            desc = desc.replace(
                " For simple information retrieval, prefer web_search or web_extract (faster, cheaper).",
                "",
            )
            filtered_tools[i] = {
                "type": "function",
                "function": {**tool["function"], "description": desc},
            }
            break
    return filtered_tools


def _replace_tool_schema(filtered_tools, tool_name: str, schema: dict[str, Any]):
    for i, tool in enumerate(filtered_tools):
        if tool.get("function", {}).get("name") == tool_name:
            filtered_tools[i] = {"type": "function", "function": schema}
            break
    return filtered_tools
