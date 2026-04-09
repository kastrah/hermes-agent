"""No-API web access helpers inspired by Agent-Reach."""

from .doctor import no_api_web_doctor
from .extract import no_api_web_extract
from .search import no_api_web_search


def check_no_api_web_available() -> bool:
    """Return whether the built-in no-API web backend is usable."""
    return True


__all__ = [
    "check_no_api_web_available",
    "no_api_web_doctor",
    "no_api_web_extract",
    "no_api_web_search",
]
