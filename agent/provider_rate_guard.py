"""Rate limit guard integration for primary provider calls.

This module provides a simple integration point for checking rate limits
before making primary provider API calls. It wraps the provider selection
logic to skip rate-limited providers.

Usage:
    from agent.provider_rate_guard import should_use_fallback, record_provider_rate_limit
    
    # Before calling primary provider:
    if should_use_fallback(provider, model):
        # Use fallback instead
        provider, model = get_fallback_provider()
    
    # After getting 429:
    record_provider_rate_limit(provider, model, error)
"""

from agent.rate_limit_guard import RateLimitStore, format_remaining

# Cache of provider fallback mappings
_fallback_mappings = {}


def set_fallback_mapping(primary_provider: str, primary_model: str, fallback_provider: str, fallback_model: str = "") -> None:
    """Configure which provider to fall back to when primary is rate-limited."""
    key = f"{primary_provider}:{primary_model}"
    _fallback_mappings[key] = {
        "provider": fallback_provider,
        "model": fallback_model,
    }


def should_use_fallback(provider: str, model: str = "") -> tuple[bool, str]:
    """Check if primary provider is rate-limited and should use fallback.
    
    Returns (should_use_fallback, reason_message)
    """
    store = RateLimitStore(provider, model)
    if store.is_limited:
        remaining = store.remaining
        reason = f"Rate-limited for {format_remaining(remaining) if remaining else 'unknown time'}"
        return True, reason
    
    # Check for general "openai-codex" to skip if any codex model is rate-limited
    if provider == "openai-codex":
        # Check generic codex rate limit
        generic_store = RateLimitStore("openai-codex", "")
        if generic_store.is_limited:
            remaining = generic_store.remaining
            return True, f"Codex rate-limited for {format_remaining(remaining) if remaining else 'unknown'}"
    
    return False, ""


def get_fallback_for(provider: str, model: str = "") -> tuple[str, str]:
    """Get fallback provider/model if primary is rate-limited."""
    key = f"{provider}:{model}"
    if key in _fallback_mappings:
        fallback = _fallback_mappings[key]
        return fallback["provider"], fallback["model"]
    
    # Generic codex fallback
    if provider == "openai-codex":
        return "nvidia-nemotron", "nvidia/nemotron-3-super-120b-a12b"
    
    return None, None


def record_provider_rate_limit(provider: str, model: str = "", headers: dict = None, error_context: dict = None) -> None:
    """Record that a provider got rate-limited."""
    RateLimitStore(provider, model).record(headers=headers, error_context=error_context, default_cooldown=300.0)


def init_from_config(config: dict) -> None:
    """Initialize fallback mappings from config.yaml."""
    global _fallback_mappings
    
    # Get fallback providers from config
    fallback_providers = config.get("fallback_providers", [])
    primary_provider = config.get("model", {}).get("provider", "")
    primary_model = config.get("model", {}).get("default", "")
    
    if fallback_providers and primary_provider:
        # Use first fallback as the primary fallback
        fb = fallback_providers[0]
        fb_provider = fb.get("provider", "")
        fb_model = fb.get("model", "")
        
        if fb_provider:
            set_fallback_mapping(primary_provider, primary_model, fb_provider, fb_model)
            
            # Also set a generic fallback for codex
            if "codex" in primary_provider.lower():
                set_fallback_mapping("openai-codex", "", fb_provider, fb_model)


def check_and_get_provider(provider: str, model: str = "") -> tuple[str, str, bool]:
    """Check if primary is rate-limited, return (provider, model, used_fallback).
    
    This is the main function to call before making an API request.
    """
    should_fallback, reason = should_use_fallback(provider, model)
    
    if should_fallback:
        fallback_provider, fallback_model = get_fallback_for(provider, model)
        if fallback_provider:
            return fallback_provider, fallback_model, True
    
    return provider, model, False