# ruff: noqa: F811
"""Staged migration preserves immutable history and conservative control state."""

import psycopg
import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.resources import resource

pytestmark = pytest.mark.integration


def test_lineage_migration_preserves_evidence_and_is_idempotent(engine):
    store = engine.host.store
    migration = resource("infrastructure/postgres/012_aegis_lineage.sql").read_text()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO core.intelligence_records(id,kind,owner,payload) VALUES ('legacy-aegis-evidence','HistoricalObservation','p2p','{\"name\":\"P2P\"}')"
        )
        conn.execute(
            "INSERT INTO core.agent_instances(id,owner,definition,status) VALUES ('legacy-aegis-agent','p2p','{\"name\":\"P2P\"}','DISABLED')"
        )
        conn.execute("INSERT INTO core.product_controls VALUES ('p2p',true),('aegis',false)")
        conn.execute("INSERT INTO core.product_stops VALUES ('p2p','legacy-stopped-work')")
        before_record = conn.execute(
            "SELECT * FROM core.intelligence_records WHERE id='legacy-aegis-evidence'"
        ).fetchone()
        before_agent = conn.execute(
            "SELECT * FROM core.agent_instances WHERE id='legacy-aegis-agent'"
        ).fetchone()
        conn.execute(migration)
        assert (
            conn.execute(
                "SELECT * FROM core.intelligence_records WHERE id='legacy-aegis-evidence'"
            ).fetchone()
            == before_record
        )
        assert (
            conn.execute(
                "SELECT * FROM core.agent_instances WHERE id='legacy-aegis-agent'"
            ).fetchone()
            == before_agent
        )
        alias = conn.execute("SELECT * FROM core.product_aliases WHERE alias='p2p'").fetchone()
        assert alias["canonical_product"] == "aegis"
        assert alias["recorded_at"].tzinfo is not None
        assert conn.execute(
            "SELECT paused FROM core.product_controls WHERE product='aegis'"
        ).fetchone()["paused"]
        assert conn.execute(
            "SELECT 1 FROM core.product_stops WHERE product='aegis' AND work_id='legacy-stopped-work'"
        ).fetchone()
        conn.execute(
            "INSERT INTO core.intelligence_records(id,kind,owner,payload) VALUES ('current-aegis-evidence','Observation','aegis','{}')"
        )
        conn.execute(
            "INSERT INTO core.agent_instances(id,owner,definition,status) VALUES ('current-aegis-agent','aegis','{}','DISABLED')"
        )
        conn.execute("UPDATE core.product_controls SET paused=false WHERE product='aegis'")
        conn.execute(migration)
        assert not conn.execute(
            "SELECT paused FROM core.product_controls WHERE product='aegis'"
        ).fetchone()["paused"]
        assert (
            conn.execute("SELECT * FROM core.product_aliases WHERE alias='p2p'").fetchone() == alias
        )
    for statement in (
        "UPDATE core.product_aliases SET canonical_product='triad' WHERE alias='p2p'",
        "DELETE FROM core.product_aliases WHERE alias='p2p'",
        "UPDATE core.intelligence_records SET owner='aegis' WHERE id='legacy-aegis-evidence'",
        "UPDATE core.agent_instances SET owner='aegis' WHERE id='legacy-aegis-agent'",
    ):
        with pytest.raises(psycopg.errors.RaiseException), store.connect() as conn:
            conn.execute(statement)
