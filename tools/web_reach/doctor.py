"""Diagnostic helpers for Hermes's no-API web reach package."""

from __future__ import annotations

import json

from .channels import get_channel_diagnostics


def no_api_web_doctor() -> str:
    """Return channel availability info as JSON."""
    return json.dumps({"channels": get_channel_diagnostics()}, indent=2, ensure_ascii=False)
