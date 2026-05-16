"""Cross-session rate limit guard for any LLM provider.

Writes rate limit state to shared files so all sessions (CLI, gateway,
cron, auxiliary) can check whether a provider is currently rate-limited
before making requests. Prevents retry amplification when RPH/TPM is tapped.

Rate limit state files are stored in ~/.hermes/rate_limits/
Each file is named: <provider>_<model>.json (normalized)
e.g.: openai-codex_gpt-5.4-mini.json, nvidia_nemotron.json

Each 429 can trigger retry amplification (3 retries x multiple attempts).
By recording the rate limit state on first 429 and checking before
subsequent requests, we eliminate this amplification effect.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

_STATE_SUBDIR = "rate_limits"


def _state_dir() -> str:
    """Return the rate limits state directory."""
    try:
        from hermes_constants import get_hermes_home
        base = get_hermes_home()
    except ImportError:
        base = os.path.join(os.path.expanduser("~"), ".hermes")
    return os.path.join(base, _STATE_SUBDIR)


def _normalize_key(provider: str, model: str = "") -> str:
    """Normalize provider/model into a safe filename key.
    
    Examples:
        openai-codex + gpt-5.4-mini -> openai-codex_gpt-5.4-mini
        nvidia-nemotron + nemotron-3-super -> nvidia_nemotron-3-super
    """
    prov = provider.lower().strip()
    # Replace colons and slashes with underscores
    prov = prov.replace("/", "_").replace(":", "_").replace("-", "_")
    model_norm = model.lower().strip().replace("/", "_").replace(":", "_").replace("-", "_") if model else ""
    return f"{prov}_{model_norm}" if model_norm else prov


def _state_path(provider: str, model: str = "") -> str:
    """Return the path to the rate limit state file for a provider."""
    key = _normalize_key(provider, model)
    return os.path.join(_state_dir(), f"{key}.json")


def _parse_reset_seconds(headers: Optional[Mapping[str, str]]) -> Optional[float]:
    """Extract reset time from response headers.

    Priority:
      1. x-ratelimit-reset-requests-1h  (hourly RPH window)
      2. x-ratelimit-reset-requests     (per-minute RPM window)
      3. x-ratelimit-reset-tokens-1h     (hourly TPM window)
      4. x-ratelimit-reset-tokens       (per-minute TPM window)
      5. retry-after                  (generic HTTP header)

    Returns seconds-from-now, or None if no usable header found.
    """
    if not headers:
        return None

    lowered = {k.lower(): v for k, v in headers.items()}

    for key in (
        "x-ratelimit-reset-requests-1h",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens-1h",
        "x-ratelimit-reset-tokens",
        "retry-after",
    ):
        raw = lowered.get(key)
        if raw is not None:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass

    return None


def record_rate_limit(
    provider: str,
    model: str = "",
    *,
    headers: Optional[Mapping[str, str]] = None,
    error_context: Optional[dict[str, Any]] = None,
    default_cooldown: float = 300.0,
) -> None:
    """Record that a provider is rate-limited.

    Parses the reset time from response headers or error context.
    Falls back to ``default_cooldown`` (5 minutes) if no reset info
    is available. Writes to a shared file that all sessions can read.

    Args:
        provider: Provider name (e.g., "openai-codex", "nvidia-nemotron")
        model: Model name (optional, for more granular tracking)
        headers: HTTP response headers from the 429 error
        error_context: Structured error context
        default_cooldown: Fallback cooldown in seconds when no header data
    """
    now = time.time()
    reset_at = None

    # Try headers first (most accurate)
    header_seconds = _parse_reset_seconds(headers)
    if header_seconds is not None:
        reset_at = now + header_seconds

    # Try error_context reset_at
    if reset_at is None and isinstance(error_context, dict):
        ctx_reset = error_context.get("reset_at")
        if isinstance(ctx_reset, (int, float)) and ctx_reset > now:
            reset_at = float(ctx_reset)
        # Also check for Retry-After header value
        elif isinstance(ctx_reset, (int, float)) and ctx_reset > 0:
            reset_at = now + float(ctx_reset)

    # Default cooldown
    if reset_at is None:
        reset_at = now + default_cooldown

    path = _state_path(provider, model)
    key = f"{provider}/{model}" if model else provider

    try:
        state_dir = _state_dir()
        os.makedirs(state_dir, exist_ok=True)

        state = {
            "reset_at": reset_at,
            "recorded_at": now,
            "reset_seconds": reset_at - now,
            "provider": provider,
            "model": model,
        }

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(
            "Rate limit recorded for %s: resets in %.0fs (at %.0f)",
            key, reset_at - now, reset_at,
        )
    except Exception as exc:
        logger.debug("Failed to write rate limit state for %s: %s", key, exc)


def rate_limit_remaining(provider: str, model: str = "") -> Optional[float]:
    """Check if a provider is currently rate-limited.

    Returns:
        Seconds remaining until reset, or None if not rate-limited.
    """
    path = _state_path(provider, model)
    try:
        with open(path) as f:
            state = json.load(f)
        reset_at = state.get("reset_at", 0)
        remaining = reset_at - time.time()
        if remaining > 0:
            return remaining
        # Expired — clean up
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return None


def is_rate_limited(provider: str, model: str = "") -> bool:
    """Check if a provider is currently rate-limited."""
    return rate_limit_remaining(provider, model) is not None


def clear_rate_limit(provider: str, model: str = "") -> None:
    """Clear the rate limit state (e.g., after a successful request)."""
    try:
        os.unlink(_state_path(provider, model))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("Failed to clear rate limit state for %s: %s", provider, exc)


def format_remaining(seconds: float) -> str:
    """Format seconds remaining into human-readable duration."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, remainder = divmod(s, 3600)
    m = remainder // 60
    return f"{h}h {m}m" if m else f"{h}h"


def get_all_rate_limits() -> dict[str, dict]:
    """Get all current rate limits (for debugging/status)."""
    state_dir = _state_dir()
    if not os.path.isdir(state_dir):
        return {}

    result = {}
    try:
        for filename in os.listdir(state_dir):
            if filename.endswith(".json"):
                path = os.path.join(state_dir, filename)
                try:
                    with open(path) as f:
                        state = json.load(f)
                    reset_at = state.get("reset_at", 0)
                    remaining = reset_at - time.time()
                    if remaining > 0:
                        provider = state.get("provider", filename[:-5])
                        model = state.get("model", "")
                        result[filename[:-5]] = {
                            "remaining": remaining,
                            "reset_at": reset_at,
                            "formatted": format_remaining(remaining),
                            "provider": provider,
                            "model": model,
                        }
                except Exception:
                    pass
    except OSError:
        pass

    return result

class RateLimitStore:
    """Deep Module for provider rate-limit state persistence."""

    def __init__(self, provider: str, model: str = ""):
        self.provider = provider
        self.model = model

    @property
    def remaining(self) -> Optional[float]:
        return rate_limit_remaining(self.provider, self.model)

    @property
    def is_limited(self) -> bool:
        return self.remaining is not None

    def record(
        self,
        *,
        headers: Optional[Mapping[str, str]] = None,
        error_context: Optional[dict[str, Any]] = None,
        default_cooldown: float = 300.0,
    ) -> None:
        record_rate_limit(
            self.provider,
            self.model,
            headers=headers,
            error_context=error_context,
            default_cooldown=default_cooldown,
        )

    def clear(self) -> None:
        clear_rate_limit(self.provider, self.model)

    def format_remaining(self) -> str:
        remaining = self.remaining
        return format_remaining(remaining) if remaining is not None else "0s"
