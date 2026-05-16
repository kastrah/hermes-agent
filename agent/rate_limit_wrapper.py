"""Rate-limit-aware provider wrapper.

Wraps provider clients to automatically detect 429s, record
rate limit state, and skip exhausted providers until reset.

Usage:
    from agent.rate_limit_wrapper import with_rate_limit_guard
    
    # Instead of: response = client.chat.completions.create(...)
    # Use: response = with_rate_limit_guard(client, "nvidia-nemotron", "nemotron-3-super")(client.chat.completions.create, **kwargs)

Or use as a decorator:
    @with_rate_limit_guard(provider="openai-codex", model="gpt-5.4-mini")
    def call_codex(**kwargs):
        return codex_client.chat.completions.create(**kwargs)
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional, TypeVar

from agent.rate_limit_guard import (
    clear_rate_limit,
    is_rate_limited,
    record_rate_limit,
    rate_limit_remaining,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_rate_limit_guard(
    provider: str,
    model: str = "",
    cooldown_on_error: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that adds rate limit awareness to provider calls.

    Usage:
        @with_rate_limit_guard(provider="openai-codex", model="gpt-5.4-mini")
        def call_codex(**kwargs):
            return client.chat.completions.create(**kwargs)

        # First call - checks rate limit first
        # If 429 - records limit, tries fallback, then retries after cooldown
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            # Check rate limit before making request
            if is_rate_limited(provider, model):
                remaining = rate_limit_remaining(provider, model)
                logger.debug(
                    "Skipping %s/%s (rate-limited, %.0fs remaining)",
                    provider, model, remaining
                )
                # Could raise a specific exception for caller to catch
                # Or return None to signal skip
                raise RateLimitError(
                    f"Provider {provider} is rate-limited. "
                    f"Try again in {remaining:.0f}s."
                )

            try:
                result = fn(*args, **kwargs)
                # Success - optionally clear rate limit
                if rate_limit_remaining(provider, model) is not None:
                    clear_rate_limit(provider, model)
                return result
            except Exception as exc:
                # Check if this is a 429
                if _is_429_error(exc) and cooldown_on_error:
                    # Try to extract headers from error
                    headers = _extract_headers(exc)
                    record_rate_limit(
                        provider, model,
                        headers=headers,
                        default_cooldown=300.0,
                    )
                    logger.info(
                        "Recorded rate limit for %s/%s after 429",
                        provider, model
                    )
                raise

        return wrapper
    return decorator


class RateLimitError(Exception):
    """Raised when a provider is or was just rate-limited."""
    pass


def _is_429_error(exc: Exception) -> bool:
    """Check if an exception indicates a 429 rate limit."""
    exc_str = str(exc).lower()
    
    # Check status code in error message
    if "429" in exc_str:
        return True
    
    # Check for common rate limit patterns
    rate_limit_patterns = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "rate limited",
        "exceeded",
        "throttl",
        "quota",
    ]
    
    for pattern in rate_limit_patterns:
        if pattern in exc_str:
            return True
    
    # Check exception type
    exc_type_name = type(exc).__name__.lower()
    if "rate" in exc_type_name or "limit" in exc_type_name:
        return True
    
    return False


def _extract_headers(exc: Exception) -> Optional[dict]:
    """Try to extract headers from an exception."""
    # Check for response object with headers
    if hasattr(exc, "response") and hasattr(exc.response, "headers"):
        return dict(exc.response.headers)
    
    # Check for headers in exception attributes
    if hasattr(exc, "headers"):
        return getattr(exc, "headers", None)
    
    if hasattr(exc, "__dict__"):
        for attr in ("response_headers", "headers", "header"):
            if attr in exc.__dict__:
                return getattr(exc, attr, None)
    
    return None


def check_and_record_rate_limit(
    provider: str,
    model: str,
    exc: Exception,
    *,
    default_cooldown: float = 300.0,
) -> bool:
    """Check if exception is a 429 and record rate limit if so.
    
    Returns True if rate limit was recorded, False otherwise.
    """
    if not _is_429_error(exc):
        return False
    
    headers = _extract_headers(exc)
    record_rate_limit(
        provider, model,
        headers=headers,
        default_cooldown=default_cooldown,
    )
    return True


def should_skip_provider(provider: str, model: str = "") -> tuple[bool, Optional[float]]:
    """Check if a provider should be skipped due to rate limiting.
    
    Returns (should_skip, seconds_remaining).
    """
    remaining = rate_limit_remaining(provider, model)
    if remaining is not None and remaining > 0:
        return True, remaining
    return False, None


# Legacy compatibility - redirect nous_rate_guard calls
def nous_rate_limit_remaining() -> Optional[float]:
    """Legacy compatibility - redirects to generic rate_limit_guard."""
    # For backwards compatibility with existing code
    return rate_limit_remaining("nous-portal")


def record_nous_rate_limit(**kwargs) -> None:
    """Legacy compatibility - redirects to generic rate_limit_guard."""
    record_rate_limit("nous-portal", **kwargs)


def clear_nous_rate_limit() -> None:
    """Legacy compatibility - redirects to generic rate_limit_guard."""
    clear_rate_limit("nous-portal")