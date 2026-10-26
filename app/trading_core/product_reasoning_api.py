"""Read-only product readings on Core's governed provider path (Mission 14 spec §4.1).

A product's worker presents its own key, never the operator token or a provider key. The key opens
only its product's reasoning route: no tools, no files, no execution, no Intake writes.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from trading_core.api import ENGINE_DEPENDENCY
from trading_core.intelligence.records import Records
from trading_core.product_reasoning import ProductReasoning, ReasoningFailed, ReasoningRequest

router = APIRouter()
PRODUCT_KEYS = {"aegis": "aegis_product_key"}  # product -> its Settings field
MIN_KEY = 32
__all__ = ["PRODUCT_KEYS", "ReasoningFailed", "ReasoningRequest", "reasoner", "router"]


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


def reasoner(engine=ENGINE_DEPENDENCY):
    """Core's governed run of a product reading, on the gateway's own store."""
    return ProductReasoning(Records(engine.store))


OWNER = Depends(require_product_key)
REASONER = Depends(reasoner)


@router.post("/api/core/products/{product}/reasoning")
def product_reasoning(request: ReasoningRequest, owner: str = OWNER, service=REASONER):
    try:
        return service.reason(owner, request)
    except ReasoningFailed as exc:
        raise HTTPException(exc.status, {"reason": exc.reason, "message": str(exc)}) from exc
