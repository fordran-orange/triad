"""Read-only product readings on Core's governed provider path (Mission 14 spec §4.1).

A product's worker presents its own key, never the operator token or a provider key. The key opens
only its product's reasoning route: no tools, no files, no execution, no Intake writes.
"""

import hmac
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field, field_validator

from trading_core.api import ENGINE_DEPENDENCY
from trading_core.work import Record

router = APIRouter()
PRODUCT_KEYS = {"aegis": "aegis_product_key"}  # product -> its Settings field
MIN_KEY = 32
SCHEMA_CHARS = 8_000


class ReasoningRequest(Record):
    provider: Literal["CODEX", "CLAUDE", "GROK"]
    instructions: str = Field(min_length=1, max_length=20_000)
    input: str = Field(min_length=1, max_length=2_000)
    output_schema: dict

    @field_validator("output_schema")
    @classmethod
    def bounded_schema(cls, value):
        if len(json.dumps(value)) > SCHEMA_CHARS:
            raise ValueError(f"output_schema over {SCHEMA_CHARS:,} characters")
        return value


class ReasoningFailed(Exception):
    """A reading that did not complete: its reason, HTTP status and a short message."""

    def __init__(self, reason: str, status: int, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason
        self.status = status


def _key(settings, field: str) -> str:
    value = getattr(settings, field, None)
    return value.get_secret_value() if value is not None else ""


def require_product_key(
    product: str, authorization: str = Header(default=""), engine=ENGINE_DEPENDENCY
) -> str:
    """The product whose key was presented; 404 unknown product, 503 no key issued, 403 another
    product's key, 401 anything else."""
    if product not in PRODUCT_KEYS:
        raise HTTPException(404, f"unknown product {product!r}")
    settings = engine.store.settings
    presented = authorization[len("Bearer ") :] if authorization.startswith("Bearer ") else ""
    own = _key(settings, PRODUCT_KEYS[product])
    if len(own) < MIN_KEY:
        raise HTTPException(503, {"reason": "not_issued", "message": "no product key issued"})
    if hmac.compare_digest(presented, own):
        return product
    for other, field in PRODUCT_KEYS.items():
        key = _key(settings, field)
        if other != product and len(key) >= MIN_KEY and hmac.compare_digest(presented, key):
            raise HTTPException(403, "that key belongs to another product")
    raise HTTPException(401, "product key required")


class _Unavailable:
    def reason(self, product, request):
        raise ReasoningFailed("unavailable", 503, "product readings are not available yet")


def reasoner(engine=ENGINE_DEPENDENCY):
    """The service that runs a reading (Task 2 supplies Core's governed run)."""
    return _Unavailable()


OWNER = Depends(require_product_key)
REASONER = Depends(reasoner)


@router.post("/api/core/products/{product}/reasoning")
def product_reasoning(request: ReasoningRequest, owner: str = OWNER, service=REASONER):
    try:
        return service.reason(owner, request)
    except ReasoningFailed as exc:
        raise HTTPException(exc.status, {"reason": exc.reason, "message": str(exc)}) from exc
