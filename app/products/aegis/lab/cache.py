"""The Lab's column cache (Optimization Lab v2 spec §9.2): a byte-bounded LRU of loaded trial
tables and experiment metadata, shared by the Lab routes of one worker.

A key is a tuple whose first element is the source tuple itself, `(("exp", id), created_at,
generation, chunk_watermark, rows, column set)` for a trial table (the document's `created_at`, so
a re-created id never meets its predecessor's tables; the row selection and the sorted column set,
so one table serves every order of its columns) and `(("exp-meta", id), updated_at)` for an
experiment's metadata, so `evict((("exp", id),))` drops every table of one experiment and nothing
else. Each value is sized by the caller's `size` callable; the total never exceeds `max_bytes`
(`LAB_CACHE_BYTES`, or `AEGIS_LAB_CACHE_MB` where the cache is built).

Arrow's allocator (mimalloc) keeps the pages of freed buffers for reuse: after a load that
works in Arrow memory (a table's read and canonical sort, an index's build: the caller says so
with `release=True`) and after an eviction, the cache hands them back to the system, so the
worker holds what the cache holds and little more."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

import pyarrow as pa

from products.aegis.lab.policy import LAB_CACHE_BYTES

T = TypeVar("T")
ENV_CACHE_MB = "AEGIS_LAB_CACHE_MB"


def cache_bytes_from_env() -> int:
    """`AEGIS_LAB_CACHE_MB` megabytes when it is set, else `LAB_CACHE_BYTES`."""
    raw = os.environ.get(ENV_CACHE_MB, "").strip()
    if not raw:
        return LAB_CACHE_BYTES
    megabytes = int(raw)
    if megabytes < 0:
        raise ValueError(f"{ENV_CACHE_MB} must be a whole number of megabytes >= 0, not {raw!r}")
    return megabytes * 1024 * 1024


def release_unused() -> None:
    """Hand the memory Arrow's pool keeps from freed buffers back to the system."""
    pa.default_memory_pool().release_unused()


class LabCache:
    """Least recently used first out, by the bytes each value's `size` reports, under one lock.
    The loader runs outside the lock, so a slow read never stalls the other routes; two requests
    that miss the same key at once both load it and the second one's value is kept."""

    def __init__(self, max_bytes: int = LAB_CACHE_BYTES) -> None:
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0

    def get(
        self,
        key: tuple,
        loader: Callable[[], T],
        *,
        size: Callable[[T], int],
        release: bool = False,
    ) -> T:
        """The cached value of `key`, else `loader()`'s, cached when `size(value)` fits within
        `max_bytes` (a larger value is returned uncached) and the oldest entries evicted until
        the total fits again. After a miss with `release` (a load in Arrow memory) or one that
        evicted, Arrow's unused memory goes back to the system."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                self._hits += 1
                return entry[0]
            self._misses += 1
        value = loader()
        nbytes = int(size(value))
        if nbytes > self.max_bytes:
            if release:
                release_unused()
            return value
        evicted = []  # dropped outside the lock, before the memory they held is released
        with self._lock:
            held = self._entries.pop(key, None)
            if held is not None:
                self._bytes -= held[1]
            self._entries[key] = (value, nbytes)
            self._bytes += nbytes
            while self._bytes > self.max_bytes:
                evicted.append(self._entries.popitem(last=False)[1])
                self._bytes -= evicted[-1][1]
        if release or evicted:
            evicted.clear()
            release_unused()
        return value

    def evict(self, prefix: tuple) -> int:
        """Remove every entry whose key starts with `prefix`; the number removed. A trial table's
        key starts with its source tuple, so an experiment's tables go with
        `evict((("exp", id),))`, never `evict(("exp", id))`."""
        with self._lock:
            gone = [key for key in self._entries if key[: len(prefix)] == prefix]
            for key in gone:
                self._bytes -= self._entries.pop(key)[1]
        if gone:
            release_unused()
        return len(gone)

    def stats(self) -> dict:
        with self._lock:
            return {
                "bytes": self._bytes,
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
            }
