"""A lineage alias cannot equate independent products or rewrite source evidence."""

import pytest
from trading_core.product_identity import (
    CURRENT_PRODUCTS,
    canonical_product,
    identity_metadata,
    lineage_owners,
    same_product,
)

pytestmark = pytest.mark.core


def test_legacy_name_is_alias_of_preserved_product_only():
    assert CURRENT_PRODUCTS == {"core", "triad", "aegis"}
    assert canonical_product("p2p") == "aegis"
    assert lineage_owners("p2p") == lineage_owners("aegis") == ("aegis", "p2p")
    assert same_product("p2p", "aegis")
    assert not same_product("triad", "aegis")
    assert not same_product("core", "p2p")
    assert lineage_owners("triad") == ("triad",)


@pytest.mark.parametrize("invalid", ["", "shared", "AEGIS", "aegis/../triad", "other"])
def test_unknown_names_cannot_become_product_authority(invalid):
    with pytest.raises(ValueError):
        canonical_product(invalid)


def test_metadata_preserves_recorded_name():
    original = {"owner": "p2p", "timestamp": "2026-09-18T00:00:00Z"}
    metadata = identity_metadata(original["owner"])
    assert metadata == {"recorded_product": "p2p", "canonical_product": "aegis"}
    assert original == {"owner": "p2p", "timestamp": "2026-09-18T00:00:00Z"}
