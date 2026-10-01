"""Narrow QA reads retain ownership and current-review authority."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store

pytestmark = pytest.mark.integration


def test_filtered_records_keep_private_owners_and_legacy_aliases(engine):
    host = Records(engine.host.store)
    ids = {
        owner: host.append("Observation", {"key": "shared-name"}, owner=owner)
        for owner in ("triad", "aegis", "p2p", "core")
    }
    for scope, expected in (("triad", {"triad"}), ("aegis", {"aegis", "p2p"})):
        records = Records(Store(engine.host.store.settings, scope=scope))
        rows = records.list("Observation", matching={"key": "shared-name"}, shared=True)
        assert {r["id"] for r in rows} == {ids[o] for o in expected}
        assert not records.list("Observation", matching={"key": "not-present"})
    assert {r["id"] for r in host.list("Observation", matching={"key": "shared-name"})} == set(
        ids.values()
    )


def test_quality_queries_only_matching_reviews_and_latest_failure_still_revokes(engine):
    records = Records(engine.host.store)
    quality = Quality(records)
    target = build(records)
    unrelated = build(records)
    quality.review(qa(unrelated, decision="REJECT"))
    passed = quality.review(qa(target))
    with records.store.connect() as conn:
        counts = []

        class Query:
            def __init__(self, cursor, capture):
                self.cursor, self.capture = cursor, capture

            def fetchone(self):
                return self.cursor.fetchone()

            def fetchall(self):
                rows = self.cursor.fetchall()
                if self.capture:
                    counts.append(len(rows))
                return rows

        class Connection:
            def execute(self, sql, params=()):
                return Query(conn.execute(sql, params), bool(params and params[0] == "QARun"))

        assert (
            quality.require_pass(
                target.implementation_run_id, target.change_commit, conn=Connection()
            )["id"]
            == passed
        )
        assert counts == [1]  # Unrelated review payloads never leave PostgreSQL.
    quality.review(qa(target, decision="REJECT"))
    with pytest.raises(PermissionError, match="Latest independent QA"):
        quality.require_pass(target.implementation_run_id, target.change_commit)
