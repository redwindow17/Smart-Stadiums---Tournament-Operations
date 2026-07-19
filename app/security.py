"""Security primitives: input sanitisation, rate limiting, response headers.

Design notes
------------
* User text is treated strictly as *data*. Before it is embedded in any
  prompt it is sanitised (control characters stripped, length capped) and it
  is always placed inside clearly delimited blocks so the model cannot be
  steered by role-play markers pasted into a message.
* Rate limiting is a per-client sliding window kept in process memory - the
  right size for a single-node demo, and swappable for Redis in production.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Deque, Dict

# Everything except printable characters, newline and tab.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Collapse runs of whitespace-only lines to keep prompts compact.
_BLANK_RUNS = re.compile(r"\n{3,}")


def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Normalise untrusted text before it is logged or embedded in a prompt."""
    cleaned = _CONTROL_CHARS.sub("", text)
    cleaned = _BLANK_RUNS.sub("\n\n", cleaned)
    return cleaned.strip()[:max_length]


class SlidingWindowRateLimiter:
    """Thread-safe per-key sliding-window rate limiter (no external deps)."""

    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if key not in self._hits and len(self._hits) >= self.max_keys:
                # Memory bound: drop the stalest bucket rather than grow forever.
                oldest = min(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0.0)
                del self._hits[oldest]
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # The frontend is fully self-contained: no external scripts, styles or fonts.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    ),
}
