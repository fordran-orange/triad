"""Authenticated service checks; JSON evidence with no credentials or raw exception strings."""

import json
import sys
import urllib.request
from datetime import UTC, datetime

import psycopg
from neo4j import GraphDatabase
from trading_core.settings import ROOT, Settings


def main():
    results = {}
    settings = Settings()
    try:
        with psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            connect_timeout=10,
        ) as conn:
            row = conn.execute("SELECT 1, current_database()").fetchone()
            assert row == (1, settings.postgres_db)
            results["postgres_python"] = {"passed": True, "database": row[1]}
            extension = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname='timescaledb'"
            ).fetchone()
            assert extension
            results["timescaledb"] = {"passed": True, "version": extension[0]}
            assert (
                conn.execute(
                    "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='core' AND hypertable_name='candles_1m'"
                ).fetchone()[0]
                == 1
            )
            results["hypertable"] = {"passed": True}
            conn.execute("CREATE TEMP TABLE day1_probe (value integer)")
            conn.execute("INSERT INTO day1_probe VALUES (42)")
            assert conn.execute("SELECT value FROM day1_probe").fetchone()[0] == 42
            results["postgres_read_write"] = {"passed": True}
            conn.rollback()
    except Exception as exc:  # noqa: BLE001 - report any check failure without leaking secrets
        results["postgres_stack"] = {"passed": False, "error_type": type(exc).__name__}
    try:
        with GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
            connection_timeout=10,
        ) as driver:
            driver.verify_connectivity()
            with driver.session() as session:
                assert session.run("RETURN 1 AS ok").single()["ok"] == 1
                constraints = {
                    r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name")
                }
                assert {
                    "dataset_id",
                    "claim_id",
                    "experiment_id",
                    "strategy_id",
                    "decision_id",
                    "source_id",
                    "artifact_id",
                } <= constraints
                with session.begin_transaction() as tx:
                    assert (
                        tx.run("CREATE (n:Day1Probe {value: 42}) RETURN n.value AS value").single()[
                            "value"
                        ]
                        == 42
                    )
                    tx.rollback()
            results["neo4j_python_read_write_constraints"] = {"passed": True}
    except Exception as exc:  # noqa: BLE001 - report any check failure without leaking secrets
        results["neo4j_stack"] = {"passed": False, "error_type": type(exc).__name__}
    try:
        with urllib.request.urlopen(
            settings.ollama_url.rstrip("/") + "/api/tags", timeout=3
        ) as response:
            models = [item["name"] for item in json.load(response)["models"]]
        results["ollama"] = {
            "optional": True,
            "running": True,
            "models": models,
            "configured_model_installed": settings.ollama_model in models,
        }
    except Exception:  # noqa: BLE001 - optional local service probe
        results["ollama"] = {"optional": True, "running": False}
    report = {"checked_at_utc": datetime.now(UTC).isoformat(), "checks": results}
    output = json.dumps(report, indent=2)
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs/health.latest.json").write_text(output + "\n")
    print(output)
    return 1 if any(r.get("passed") is False for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
