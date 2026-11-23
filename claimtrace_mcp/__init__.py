"""ClaimTrace: check every number in an AI-written document against its source.

    >>> import claimtrace_mcp
    >>> result = claimtrace_mcp.check("Unemployment was 4.1% in June.", ["https://example.gov/release"])
    >>> result["summary"]
    {'total': 1, 'supported': 1, 'mismatch': 0, 'unsupported': 0, 'errors': 0}
"""

from .client import (
    DEFAULT_API_BASE,
    APIError,
    AuthError,
    ClaimTraceError,
    RateLimitError,
    UnavailableError,
    check,
    get_badge,
    get_report,
    source_spec,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_API_BASE", "APIError", "AuthError", "ClaimTraceError", "RateLimitError", "UnavailableError",
    "check", "get_badge", "get_report", "source_spec", "__version__",
]
