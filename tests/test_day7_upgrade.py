# ruff: noqa: F811
"""Exercise the deployment entry point against a real pre-upgrade database."""

import os
import subprocess
import sys

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.store import Store
from trading_core.upgrade import upgrade

pytestmark = [pytest.mark.integration, pytest.mark.core]


def test_packaged_upgrade_applies_missing_lineage_and_preserves_resume(engine):
    store = engine.host.store
    with store.connect() as conn:
        conn.execute("DROP TABLE core.product_aliases")
        conn.execute("DELETE FROM core.schema_migrations WHERE version='012_aegis_lineage'")
        conn.execute("INSERT INTO core.product_controls VALUES ('p2p',true)")
        before = conn.execute("SELECT * FROM core.intelligence_records ORDER BY id").fetchall()
    result = subprocess.run(
        [sys.executable, "-m", "trading_core.upgrade"],
        env={**os.environ, "POSTGRES_DB": store.settings.postgres_db},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    with store.connect() as conn:
        assert conn.execute("SELECT canonical_product FROM core.product_aliases").fetchone() == {
            "canonical_product": "aegis"
        }
        assert conn.execute(
            "SELECT paused FROM core.product_controls WHERE product='aegis'"
        ).fetchone()["paused"]
        assert (
            conn.execute("SELECT * FROM core.intelligence_records ORDER BY id").fetchall() == before
        )
        conn.execute("UPDATE core.product_controls SET paused=false WHERE product='aegis'")
    upgrade(store)
    with store.connect() as conn:
        assert not conn.execute(
            "SELECT paused FROM core.product_controls WHERE product='aegis'"
        ).fetchone()["paused"]
    with pytest.raises(PermissionError):
        upgrade(Store(store.settings, scope="aegis"))
