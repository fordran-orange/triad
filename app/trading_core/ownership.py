"""Host-selected product scope; product records are private unless explicitly shared."""

from trading_core.product_identity import CURRENT_PRODUCTS, lineage_owners

PRODUCTS = CURRENT_PRODUCTS
SHARED_INFRASTRUCTURE = frozenset({"Agent", "ProviderPolicy", "TransportStatus", "ProviderHealth"})


def permits(scope, owner, kind=None):
    return (
        scope is None
        or owner == "shared"
        or owner in lineage_owners(scope)
        or (owner == "core" and kind in SHARED_INFRASTRUCTURE)
    )


def require_owner(scope, owner, kind=None):
    if not permits(scope, owner, kind):
        raise PermissionError("Record belongs to another product")


def require_write(scope, owner):
    if scope is not None and owner not in lineage_owners(scope):
        raise PermissionError("Product cannot modify shared or foreign records")
