"""Two-phase synthetic probe: prepare, recreate containers, then verify-cleanup."""

import json
import sys
import uuid

import psycopg
from neo4j import GraphDatabase
from psycopg.types.json import Jsonb
from triad.settings import ROOT, Settings


def main():
    mode = sys.argv[1]
    path = ROOT / "logs/persistence-probe.json"
    settings = Settings()
    if mode == "prepare":
        if path.exists() and json.loads(path.read_text()).get("synthetic_records") != "removed":
            raise RuntimeError("Previous probe exists; verify-cleanup before preparing again")
        probe_id = "day1-persistence-" + str(uuid.uuid4())
        path.write_text(json.dumps({"probe_id": probe_id}))
    elif mode == "verify-cleanup":
        probe_id = json.loads(path.read_text())["probe_id"]
    else:
        raise ValueError("Expected prepare or verify-cleanup")
    with psycopg.connect(  # noqa: SIM117 - explicit independent database lifetimes
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        connect_timeout=10,
    ) as conn:
        with GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        ) as driver:
            with driver.session() as session:
                if mode == "prepare":
                    conn.execute(
                        "INSERT INTO triad.operational_state (key, value) VALUES (%s, %s)",
                        (probe_id, Jsonb({"synthetic_probe": 42})),
                    )
                    session.run(
                        "CREATE (:Day1PersistenceProbe {id:$id, value:42})", id=probe_id
                    ).consume()
                else:
                    assert conn.execute(
                        "SELECT value FROM triad.operational_state WHERE key=%s", (probe_id,)
                    ).fetchone()[0] == {"synthetic_probe": 42}
                    assert (
                        session.run(
                            "MATCH (n:Day1PersistenceProbe {id:$id}) RETURN n.value AS value",
                            id=probe_id,
                        ).single()["value"]
                        == 42
                    )
                    conn.execute("DELETE FROM triad.operational_state WHERE key=%s", (probe_id,))
                    session.run(
                        "MATCH (n:Day1PersistenceProbe {id:$id}) DELETE n", id=probe_id
                    ).consume()
    if mode == "verify-cleanup":
        path.write_text(
            json.dumps(
                {
                    "probe_id": probe_id,
                    "postgres": "persisted",
                    "neo4j": "persisted",
                    "synthetic_records": "removed",
                },
                indent=2,
            )
        )
    print(f"{mode}: PostgreSQL and Neo4j synthetic probe passed")


if __name__ == "__main__":
    main()
