"""The Lab's column cache (Optimization Lab v2 spec §9.2): a byte-bounded LRU of loaded trial
tables and experiment metadata, shared by the Lab routes of one worker.

A key is a tuple whose first element is the source tuple itself, `(("exp", id), created_at,
generation, chunk_watermark, columns)` for a trial table (the document's `created_at`, so a
re-created id never meets its predecessor's tables) and `(("exp-meta", id), updated_at)` for an
experiment's metadata, so `evict((("exp", id),))` drops every table of one experiment and nothing
else. Each value is sized by the caller's `size` callable; the total never exceeds `max_bytes`
(`LAB_CACHE_BYTES`, or `AEGIS_LAB_CACHE_MB` where the cache is built)."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

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

    def get(self, key: tuple, loader: Callable[[], T], *, size: Callable[[T], int]) -> T:
        """The cached value of `key`, else `loader()`'s, cached when `size(value)` fits within
        `max_bytes` (a larger value is returned uncached) and the oldest entries evicted until
        the total fits again."""
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
            return value
        with self._lock:
            held = self._entries.pop(key, None)
            if held is not None:
                self._bytes -= held[1]
            self._entries[key] = (value, nbytes)
            self._bytes += nbytes
            while self._bytes > self.max_bytes:
                _, (_, freed) = self._entries.popitem(last=False)
                self._bytes -= freed
        return value

    def evict(self, prefix: tuple) -> int:
        """Remove every entry whose key starts with `prefix`; the number removed. A trial table's
        key starts with its source tuple, so an experiment's tables go with
        `evict((("exp", id),))`, never `evict(("exp", id))`."""
        with self._lock:
            gone = [key for key in self._entries if key[: len(prefix)] == prefix]
            for key in gone:
                self._bytes -= self._entries.pop(key)[1]
            return len(gone)

    def stats(self) -> dict:
        with self._lock:
            return {
                "bytes": self._bytes,
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
            }
