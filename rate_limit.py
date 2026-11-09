"""
Per-user sliding-window rate limits — protects LLM credits from runaway or abusive use.

In-process state is sufficient while the API runs on a single Fly machine; move to
Redis or Postgres if the API is ever scaled horizontally. Platform admins (including
the eval service key) are exempt so golden-set runs are not throttled.

Environment:
    QUERY_RATE_LIMIT   Queries per user per hour (default 30)
    INGEST_RATE_LIMIT  Uploads per user per hour (default 10)
"""

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from auth import Principal, require_user


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Record a hit for key. Returns 0 if allowed, else seconds until a slot frees up."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return int(self.window_s - (now - hits[0])) + 1
            hits.append(now)
            return 0


_query_limiter = SlidingWindowLimiter(int(os.getenv("QUERY_RATE_LIMIT", "30")), 3600)
_ingest_limiter = SlidingWindowLimiter(int(os.getenv("INGEST_RATE_LIMIT", "10")), 3600)


def _enforce(limiter: SlidingWindowLimiter, principal: Principal) -> Principal:
    if principal.is_admin:
        return principal
    wait = limiter.retry_after(principal.user_id)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached. Try again in {wait // 60 + 1} minutes.",
            headers={"Retry-After": str(wait)},
        )
    return principal


def limit_queries(principal: Principal = Depends(require_user)) -> Principal:
    return _enforce(_query_limiter, principal)


def limit_ingests(principal: Principal = Depends(require_user)) -> Principal:
    return _enforce(_ingest_limiter, principal)
