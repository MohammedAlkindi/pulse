"""Exponential-backoff retry decorator for external API calls."""

import logging
import time
from functools import wraps
from typing import Callable, Tuple, Type

logger = logging.getLogger(__name__)


def with_retry(
    *,
    label: str = "call",
    max_attempts: int = 3,
    base_delay: float = 2.0,
    backoff: float = 2.0,
    retryable: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator factory.  Any exception in `retryable` triggers a retry;
    others propagate immediately.  On exhaustion the last exception re-raises.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retryable as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        "[retry] %s — attempt %d/%d failed: %s. Retrying in %.1fs.",
                        label, attempt, max_attempts, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= backoff
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
