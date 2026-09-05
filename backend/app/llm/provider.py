"""Provider-independent LLM abstractions/common logic — architecture.md
§11a. Shared by every adapter so retry/backoff and schema-extraction
behavior is implemented once, not per-provider.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


def json_schema_for(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


def retry_once_with_backoff(fn: Callable[[], T], *, backoff_seconds: float = 1.0, non_retryable: tuple[type[Exception], ...] = ()) -> T:
    """architecture.md §38: "Retry once w/ backoff, then last valid partial
    state" — the retry-once mechanic, generic across providers. Exceptions
    in `non_retryable` (e.g. a missing API key) are never retried — no
    amount of waiting fixes a configuration error.
    """
    try:
        return fn()
    except non_retryable:
        raise
    except Exception:
        if backoff_seconds > 0:
            time.sleep(backoff_seconds)
        return fn()
