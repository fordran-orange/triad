"""Canonical product lineage names without changing historical evidence bytes.

The legacy spelling is a fixed alias, not another product or an access grant.
Consumers must still apply their normal ownership checks after resolving it.
"""

CURRENT_PRODUCTS = frozenset({"core", "triad", "aegis"})
LEGACY_ALIASES = {"p2p": "aegis"}


def canonical_product(identifier: str) -> str:
    canonical = LEGACY_ALIASES.get(identifier, identifier)
    if canonical not in CURRENT_PRODUCTS:
        raise ValueError("Unknown product identity")
    return canonical


def lineage_owners(identifier: str) -> tuple[str, ...]:
    """Stored owner spellings in this lineage, suitable for parameterized queries."""
    canonical = canonical_product(identifier)
    return ("aegis", "p2p") if canonical == "aegis" else (canonical,)


def same_product(left: str, right: str) -> bool:
    return canonical_product(left) == canonical_product(right)


def identity_metadata(identifier: str) -> dict[str, str]:
    """A separate current-name annotation; never rewrite the source record."""
    return {"recorded_product": identifier, "canonical_product": canonical_product(identifier)}
