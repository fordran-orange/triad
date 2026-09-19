"""Explicit, transactional upgrades for an initialized Core installation.

Run ``python -m trading_core.upgrade`` before deploying a new release. Ordinary
service startup remains independent of database availability for diagnostics.
"""

from trading_core.resources import resource
from trading_core.store import Store


def upgrade(store=None):
    store = store or Store()
    if store.scope is not None:
        raise PermissionError("Database upgrades require the Core operator")
    with store.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('core-schema-upgrade',0))")
        if not conn.execute(
            "SELECT 1 FROM core.schema_migrations WHERE version='011_agent_lifecycle'"
        ).fetchone():
            raise RuntimeError("Initialize the Day 6 database before upgrading")
        conn.execute(
            resource("infrastructure/postgres/012_aegis_lineage.sql").read_text(encoding="utf-8")
        )
        alias = conn.execute(
            "SELECT canonical_product FROM core.product_aliases WHERE alias='p2p'"
        ).fetchone()
        if not alias or alias["canonical_product"] != "aegis":
            raise RuntimeError("Aegis lineage verification failed")
        conn.execute(
            resource("infrastructure/postgres/013_resource_allocations.sql").read_text(
                encoding="utf-8"
            )
        )
    return "Core database upgrade verified: 012_aegis_lineage, 013_resource_allocations"


if __name__ == "__main__":
    print(upgrade())
