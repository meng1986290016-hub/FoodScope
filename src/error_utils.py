"""Safe, bounded diagnostic strings for persisted or transmitted artifacts."""

from __future__ import annotations


def safe_error_detail(error: BaseException | None, context: str) -> str:
    """Describe a failure without retaining provider-controlled text."""

    error_type = type(error).__name__ if error is not None else "UnknownError"
    return f"{context} ({error_type})"
