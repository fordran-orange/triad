# ruff: noqa: F811
"""Canonical data, context, artifact and governance product boundaries."""

import pytest
from test_day3_integration import engine  # noqa: F401 - isolated DB fixture
from trading_core.context import packet_for
from trading_core.execution import ExecutionServices
from trading_core.gateway import ToolGateway
from trading_core.ledger import Stopped
from trading_core.research.service import Laboratory
from trading_core.store import Store
from trading_core.work import WorkItem

pytestmark = pytest.mark.integration


def test_aegis_reads_legacy_owner_without_rewriting_history(engine):
    from trading_core.intelligence.records import Records

    engine.host.store.create(
        WorkItem(owner="p2p", title="Preserved record", description="Legacy private evidence")
    )
    # Store.create returns no value; select only the unique disposable legacy work.
    legacy = next(w for w in engine.host.store.list_work() if w.title == "Preserved record")
    identifier = Records(engine.host.store).append("Observation", {"name": "P2P"}, owner="p2p")
    aegis = scoped(engine, "aegis")
    assert Store(engine.host.store.settings, scope="p2p").scope == "aegis"
    assert aegis.host.store.get(legacy.work_item_id).owner == "p2p"
    assert legacy.work_item_id in {w.work_item_id for w in aegis.host.store.list_work()}
    assert Records(aegis.host.store).get(identifier)["name"] == "P2P"
    assert identifier in {r["id"] for r in Records(aegis.host.store).list("Observation")}
    child = aegis.host.create(
        WorkItem(
            title="Current identity",
            description="Same lineage",
            parent_work_item_id=legacy.work_item_id,
        )
    )
    assert child.owner == "aegis"
    with pytest.raises(PermissionError):
        scoped(engine, "triad").host.store.get(legacy.work_item_id)
    aegis.ledger.operate("pause")
    with pytest.raises(Stopped):
        engine.ledger.guard(work_id=legacy.work_item_id)
    aegis.ledger.operate("resume")
    aegis.ledger.operate("stop", work_id=legacy.work_item_id)
    with pytest.raises(Stopped):
        engine.ledger.guard(work_id=legacy.work_item_id)
    assert engine.host.store.get(legacy.work_item_id).owner == "p2p"


def scoped(engine, owner):
    return ExecutionServices(Store(engine.host.store.settings, scope=owner), git=engine.git)


def test_private_records_context_and_artifacts(engine, tmp_path):
    triad, aegis = scoped(engine, "triad"), scoped(engine, "aegis")
    a = triad.host.create(WorkItem(title="Triad", description="own question"))
    b = aegis.host.create(
        WorkItem(title="Aegis private", description="private conclusion", mission_id=a.mission_id)
    )
    journal = aegis.host.journal(
        b, kind="creation", result="Aegis_PRIVATE_MARKER", mode="deterministic_demo"
    )
    aegis.host.store.add_record(journal)
    record = aegis.ledger.put("Hypothesis", {"text": "Aegis_PRIVATE_MARKER"})
    assert not triad.host.store.records("JournalEntry")
    assert (
        "Aegis_PRIVATE_MARKER"
        not in packet_for(a, triad.host.store.records("JournalEntry")).model_dump_json()
    )
    for operation in (
        lambda: triad.host.store.get(b.work_item_id),
        lambda: triad.host.store.events(b.work_item_id),
        lambda: triad.ledger.get(record),
        lambda: triad.ledger.put("Hypothesis", {"text": "overwrite"}, record),
        lambda: triad.host.create(
            WorkItem(title="cross", description="cross", parent_work_item_id=b.work_item_id)
        ),
    ):
        with pytest.raises(PermissionError):
            operation()
    assert aegis.ledger.get(record)["text"] == "Aegis_PRIVATE_MARKER"
    with pytest.raises(PermissionError):
        aegis.host.store.get(a.work_item_id)
    assert [w.work_item_id for w in aegis.host.store.list_work()] == [b.work_item_id]
    private = tmp_path / "research/generated/aegis/private.md"
    private.parent.mkdir(parents=True)
    private.write_text("Aegis_PRIVATE_MARKER")
    grant = a.model_copy(update={"allowed_paths": ("research/generated",)})
    with pytest.raises(PermissionError):
        ToolGateway(grant, tmp_path).read("research/generated/aegis/private.md")
    grant = b.model_copy(update={"allowed_paths": ("research/generated",)})
    assert (
        ToolGateway(grant, tmp_path).read("research/generated/aegis/private.md")
        == "Aegis_PRIVATE_MARKER"
    )
    # Research services cannot bypass record ownership by requesting another ID.
    with pytest.raises(PermissionError):
        Laboratory(triad).ledger.get(record)


def test_product_controls_cannot_relax_global_governance(engine):
    triad = scoped(engine, "triad")
    work = triad.host.create(WorkItem(title="isolated", description="test"))
    foreign = scoped(engine, "aegis").host.create(WorkItem(title="private", description="test"))
    with pytest.raises(PermissionError):
        triad.ledger.guard(work_id=foreign.work_item_id)
    with pytest.raises(KeyError):
        triad.ledger.guard(work_id="missing-assignment")
    epoch = triad.ledger.guard(work_id=work.work_item_id)["epoch"]
    for action in ("enable", "lower_limits", "kill", "human_review"):
        with pytest.raises(PermissionError):
            triad.ledger.operate(action, agent="CODEX")
    triad.ledger.operate("pause")
    with pytest.raises(Stopped):
        triad.ledger.guard(work_id=work.work_item_id)
    triad.ledger.operate("resume")
    engine.ledger.operate("kill")
    triad.ledger.operate("resume")
    with pytest.raises(Stopped):
        triad.ledger.guard(work_id=work.work_item_id)
    engine.ledger.operate("resume")
    with pytest.raises(Stopped):
        triad.ledger.guard(work_id=work.work_item_id, epoch=epoch)
    triad.ledger.operate("stop", work_id=work.work_item_id)
    with pytest.raises(Stopped):
        triad.ledger.guard(work_id=work.work_item_id)


def test_owner_column_and_shared_writes_are_protected(engine):
    import psycopg

    triad = scoped(engine, "triad")
    work = triad.host.create(WorkItem(title="ownership", description="immutable"))
    with pytest.raises(psycopg.errors.RaiseException), engine.host.store.connect() as conn:
        conn.execute("UPDATE core.work_items SET owner='aegis' WHERE id=%s", (work.work_item_id,))
    identifier = engine.ledger.put("DatasetManifest", {"test": True})
    with engine.host.store.connect() as conn:
        conn.execute("UPDATE core.day3_records SET owner='shared' WHERE id=%s", (identifier,))
    assert triad.ledger.get(identifier)["test"]
    with pytest.raises(PermissionError):
        triad.ledger.put("DatasetManifest", {"test": False}, identifier)


def test_graph_traversal_cannot_cross_product_knowledge(engine):
    from trading_core.brain import Brain

    triad, aegis = scoped(engine, "triad"), scoped(engine, "aegis")
    a = triad.host.create(WorkItem(title="Triad graph", description="own work"))
    b = aegis.host.create(
        WorkItem(title="Aegis graph", description="private", mission_id=a.mission_id)
    )
    journal = aegis.host.journal(
        b, kind="creation", result="PRIVATE_GRAPH_MARKER", mode="deterministic_demo"
    )
    aegis.host.store.add_record(journal)
    graph = Brain(triad.host.store)
    forged = aegis.ledger.put(
        "PrivateNote",
        {"owner": "triad", "work_item_id": a.work_item_id, "status": "PRIVATE_GRAPH_MARKER"},
    )
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        # Even a bad historical edge must not expose the foreign record.
        session.run(
            "MATCH (a:WorkItem {id:$a}), (b:JournalEntry {id:$b}) MERGE (a)-[:SUPPORTED_BY]->(b)",
            a=a.work_item_id,
            b=journal.journal_id,
        ).consume()
        assert (
            session.run("MATCH (n {id:$id}) RETURN n.owner AS owner", id=forged).single()["owner"]
            == "aegis"
        )
    lineage = graph.lineage(a.work_item_id)
    assert journal.journal_id not in {row["id"] for row in lineage}
    assert forged not in {row["id"] for row in lineage}
    assert "triad:" + a.mission_id in {row["id"] for row in lineage}
    with pytest.raises(PermissionError):
        graph.lineage(b.work_item_id)
    assert journal.journal_id in {
        row["id"] for row in Brain(aegis.host.store).lineage(b.work_item_id)
    }
