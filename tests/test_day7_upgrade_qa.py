"""Independent failure-path QA of transactional upgrades; disposable DB only."""
# ruff: noqa: F811

import importlib
from pathlib import Path

import psycopg
import pytest
from test_day3_integration import engine  # noqa: F401

upgrade_module = importlib.import_module("trading_core.upgrade")
pytestmark = [pytest.mark.integration, pytest.mark.core]


def test_upgrade_missing_precondition_does_not_apply_migration(engine):
    store = engine.host.store
    with store.connect() as conn:
        conn.execute("DROP TABLE core.product_aliases")
        conn.execute(
            "DELETE FROM core.schema_migrations WHERE version IN ('011_agent_lifecycle','012_aegis_lineage')"
        )
    with pytest.raises(RuntimeError, match="Initialize the Day 6"):
        upgrade_module.upgrade(store)
    with store.connect() as conn:
        assert (
            conn.execute("SELECT to_regclass('core.product_aliases') AS name").fetchone()["name"]
            is None
        )
        assert not conn.execute(
            "SELECT 1 FROM core.schema_migrations WHERE version='012_aegis_lineage'"
        ).fetchone()


def test_late_upgrade_failure_rolls_back_all_lineage_changes(engine, tmp_path, monkeypatch):
    store = engine.host.store
    sql = upgrade_module.resource("infrastructure/postgres/012_aegis_lineage.sql").read_text(
        encoding="utf-8"
    )
    broken_resource = tmp_path / "migration.sql"
    broken_resource.write_text(sql + "\nSELECT 1/0;\n", encoding="utf-8")
    with store.connect() as conn:
        conn.execute("DROP TABLE core.product_aliases")
        conn.execute("DELETE FROM core.schema_migrations WHERE version='012_aegis_lineage'")
        conn.execute("DELETE FROM core.product_controls WHERE product='aegis'")
        conn.execute("INSERT INTO core.product_controls VALUES ('p2p',true)")
        conn.execute("INSERT INTO core.product_stops VALUES ('p2p','legacy-stop')")
    monkeypatch.setattr(upgrade_module, "resource", lambda _: Path(broken_resource))
    with pytest.raises(psycopg.errors.DivisionByZero):
        upgrade_module.upgrade(store)
    with store.connect() as conn:
        assert (
            conn.execute("SELECT to_regclass('core.product_aliases') AS name").fetchone()["name"]
            is None
        )
        assert not conn.execute(
            "SELECT 1 FROM core.schema_migrations WHERE version='012_aegis_lineage'"
        ).fetchone()
        assert not conn.execute(
            "SELECT 1 FROM core.product_controls WHERE product='aegis'"
        ).fetchone()
        assert not conn.execute("SELECT 1 FROM core.product_stops WHERE product='aegis'").fetchone()
        assert conn.execute(
            "SELECT paused FROM core.product_controls WHERE product='p2p'"
        ).fetchone()["paused"]
