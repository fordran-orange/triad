"""The Aegis worker's client for Core's read-only reasoning route (Mission 14 spec §4.1–4.2).

The worker presents its own product key, never the operator token; Core answers with the JSON and
its provenance, or a reason the worker shows the operator.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

CORE_URL = os.environ.get("AEGIS_CORE_URL", "http://127.0.0.1:8000")
TIMEOUT_SECONDS = 125.0  # Core's own limit is 120 s
MIN_KEY = 32


class CoreReadingError(Exception):
    """A reading Core did not give: the HTTP status, Core's reason and its message."""

    def __init__(self, status: int, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.status = status
        self.reason = reason


class CoreReasoning:
    def __init__(self, base: str = CORE_URL, key: str = ""):
        self.base = base.rstrip("/")
        self.key = key

    def reason(self, provider: str, instructions: str, input: str, output_schema: dict) -> dict:
        if len(self.key) < MIN_KEY:
            raise CoreReadingError(503, "not_issued", "no product key issued")
        request = urllib.request.Request(
            f"{self.base}/api/core/products/aegis/reasoning",
            data=json.dumps(
                {
                    "provider": provider,
                    "instructions": instructions,
                    "input": input,
                    "output_schema": output_schema,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, dict):
                raise CoreReadingError(
                    exc.code, str(detail.get("reason", "failed")), str(detail.get("message", ""))
                ) from exc
            reason = {401: "refused", 403: "refused", 404: "refused"}.get(exc.code, "failed")
            raise CoreReadingError(exc.code, reason, str(detail or exc.reason)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CoreReadingError(503, "core_unavailable", "Core is not answering") from exc


__all__ = ["CORE_URL", "CoreReadingError", "CoreReasoning"]
