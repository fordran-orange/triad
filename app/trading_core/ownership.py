"""Host-selected product scope; product records are private unless explicitly shared."""

PRODUCTS = frozenset({"core", "p2p", "triad"})
SHARED_INFRASTRUCTURE = frozenset({"Agent", "ProviderPolicy", "TransportStatus", "ProviderHealth"})


def permits(scope, owner, kind=None):
    return (
        scope is None
        or owner in {scope, "shared"}
        or (owner == "core" and kind in SHARED_INFRASTRUCTURE)
    )


def require_owner(scope, owner, kind=None):
    if not permits(scope, owner, kind):
        raise PermissionError("Record belongs to another product")


def require_write(scope, owner):
    if scope is not None and scope != owner:
        raise PermissionError("Product cannot modify shared or foreign records")
