"""A deliberately tiny TTL cache.

At this data scale (a few hundred meters, ~40 transformers) an in-memory
dict with a timestamp is all that's needed — reaching for Redis or a real
cache library would be over-engineering for a single-process read-through
proxy. See README "What I'd improve" for where this stops scaling.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    fetched_at: float


class TTLCache(Generic[T]):
    """Single-value cache: one cached blob (e.g. "all meters"), refreshed
    via an async loader function once its TTL has elapsed.

    A lock ensures concurrent callers arriving while the cache is cold (or
    stale) don't all fire the loader at once — the first caller populates
    it, everyone else waits and reuses the result.
    """

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._entry: _Entry[T] | None = None
        self._lock = asyncio.Lock()

    def age_seconds(self) -> float | None:
        if self._entry is None:
            return None
        return time.monotonic() - self._entry.fetched_at

    def _is_fresh(self) -> bool:
        age = self.age_seconds()
        return age is not None and age < self._ttl

    async def get(self, loader) -> T:
        if self._is_fresh():
            return self._entry.value  # type: ignore[union-attr]
        async with self._lock:
            # Re-check: another caller may have refreshed while we waited.
            if not self._is_fresh():
                value = await loader()
                self._entry = _Entry(value=value, fetched_at=time.monotonic())
        return self._entry.value  # type: ignore[union-attr]

    def invalidate(self) -> None:
        self._entry = None


class KeyedTTLCache(Generic[T]):
    """Per-key variant, used for per-meter consumption readings.

    Bounded with a simple max-size + oldest-first eviction so a caller
    scripting through all 403 meters can't grow this unboundedly — good
    enough here; a real LRU would be the upgrade if the meter count grew by
    orders of magnitude.
    """

    def __init__(self, ttl_seconds: float, max_size: int = 1000):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._entries: dict[str, _Entry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str, loader) -> T:
        entry = self._entries.get(key)
        if entry is not None and (time.monotonic() - entry.fetched_at) < self._ttl:
            return entry.value

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._entries.get(key)
            if entry is None or (time.monotonic() - entry.fetched_at) >= self._ttl:
                value = await loader()
                if len(self._entries) >= self._max_size:
                    oldest_key = min(self._entries, key=lambda k: self._entries[k].fetched_at)
                    self._entries.pop(oldest_key, None)
                    self._locks.pop(oldest_key, None)
                self._entries[key] = _Entry(value=value, fetched_at=time.monotonic())
                entry = self._entries[key]
        return entry.value
