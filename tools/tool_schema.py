"""Tool schema assembly behind a single deep Module."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool-name resolution — extracted from model_tools._compute_tool_definitions
# so the schema assembly module is self-contained.
# ---------------------------------------------------------------------------

_LEGACY_TOOLSET_MAP: dict[str, set[str]] = {}  # populated at registry init


def resolve_tool_names(
    enabled_toolsets: list[str] | None = None,
    disabled_toolsets: list[str] | None = None,
    quiet_mode: bool = False,
    registry: Any = None,
) -> set[str]:
    """Resolve the set of tool names from toolset specifiers.

    Mirrors the upstream logic in model_tools._compute_tool_definitions
    (v0.14.0, lines 327–373).  Supports enabled/disjoint/legacy toolsets.
    """
    from toolsets import resolve_toolset, validate_toolset, get_all_toolsets

    tools_to_include: set[str] = set()

    if enabled_toolsets is not None:
        for toolset_name in enabled_toolsets:
            if validate_toolset(toolset_name):
                resolved = resolve_toolset(toolset_name)
                tools_to_include.update(resolved)
                if not quiet_mode:
                    print(f"✅ Enabled toolset '{toolset_name}': {', '.join(resolved) if resolved else 'no tools'}")
            elif toolset_name in _LEGACY_TOOLSET_MAP:
                legacy_tools = _LEGACY_TOOLSET_MAP[toolset_name]
                tools_to_include.update(legacy_tools)
                if not quiet_mode:
                    print(f"✅ Enabled legacy toolset '{toolset_name}': {', '.join(legacy_tools)}")
            elif not quiet_mode:
                print(f"⚠️  Unknown toolset: {toolset_name}")
    else:
        for ts_name in get_all_toolsets():
            tools_to_include.update(resolve_toolset(ts_name))

    if disabled_toolsets:
        for toolset_name in disabled_toolsets:
            if validate_toolset(toolset_name):
                resolved = resolve_toolset(toolset_name)
                tools_to_include.difference_update(resolved)
                if not quiet_mode:
                    print(f"🚫 Disabled toolset '{toolset_name}': {', '.join(resolved) if resolved else 'no tools'}")
            elif toolset_name in _LEGACY_TOOLSET_MAP:
                legacy_tools = _LEGACY_TOOLSET_MAP[toolset_name]
                tools_to_include.difference_update(legacy_tools)
                if not quiet_mode:
                    print(f"🚫 Disabled legacy toolset '{toolset_name}': {', '.join(legacy_tools)}")
            elif not quiet_mode:
                print(f"⚠️  Unknown toolset: {toolset_name}")

    return tools_to_include


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
    filtered_tools = registry.get_definitions(plan, quiet=quiet_mode)
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
