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


def scoped(engine, owner):
    return ExecutionServices(Store(engine.host.store.settings, scope=owner), git=engine.git)


def test_private_records_context_and_artifacts(engine, tmp_path):
    triad, p2p = scoped(engine, "triad"), scoped(engine, "p2p")
    a = triad.host.create(WorkItem(title="Triad", description="own question"))
    b = p2p.host.create(
        WorkItem(title="P2P private", description="private conclusion", mission_id=a.mission_id)
    )
    journal = p2p.host.journal(
        b, kind="creation", result="P2P_PRIVATE_MARKER", mode="deterministic_demo"
    )
    p2p.host.store.add_record(journal)
    record = p2p.ledger.put("Hypothesis", {"text": "P2P_PRIVATE_MARKER"})
    assert not triad.host.store.records("JournalEntry")
    assert (
        "P2P_PRIVATE_MARKER"
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
    assert p2p.ledger.get(record)["text"] == "P2P_PRIVATE_MARKER"
    with pytest.raises(PermissionError):
        p2p.host.store.get(a.work_item_id)
    assert [w.work_item_id for w in p2p.host.store.list_work()] == [b.work_item_id]
    private = tmp_path / "research/generated/p2p/private.md"
    private.parent.mkdir(parents=True)
    private.write_text("P2P_PRIVATE_MARKER")
    grant = a.model_copy(update={"allowed_paths": ("research/generated",)})
    with pytest.raises(PermissionError):
        ToolGateway(grant, tmp_path).read("research/generated/p2p/private.md")
    grant = b.model_copy(update={"allowed_paths": ("research/generated",)})
    assert (
        ToolGateway(grant, tmp_path).read("research/generated/p2p/private.md")
        == "P2P_PRIVATE_MARKER"
    )
    # Research services cannot bypass record ownership by requesting another ID.
    with pytest.raises(PermissionError):
        Laboratory(triad).ledger.get(record)


def test_product_controls_cannot_relax_global_governance(engine):
    triad = scoped(engine, "triad")
    work = triad.host.create(WorkItem(title="isolated", description="test"))
    foreign = scoped(engine, "p2p").host.create(WorkItem(title="private", description="test"))
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
        conn.execute("UPDATE core.work_items SET owner='p2p' WHERE id=%s", (work.work_item_id,))
    identifier = engine.ledger.put("DatasetManifest", {"test": True})
    with engine.host.store.connect() as conn:
        conn.execute("UPDATE core.day3_records SET owner='shared' WHERE id=%s", (identifier,))
    assert triad.ledger.get(identifier)["test"]
    with pytest.raises(PermissionError):
        triad.ledger.put("DatasetManifest", {"test": False}, identifier)


def test_graph_traversal_cannot_cross_product_knowledge(engine):
    from trading_core.brain import Brain
    triad, p2p = scoped(engine, "triad"), scoped(engine, "p2p")
    a = triad.host.create(WorkItem(title="Triad graph", description="own work"))
    b = p2p.host.create(WorkItem(title="P2P graph", description="private", mission_id=a.mission_id))
    journal = p2p.host.journal(b, kind="creation", result="PRIVATE_GRAPH_MARKER", mode="deterministic_demo")
    p2p.host.store.add_record(journal)
    graph = Brain(triad.host.store)
    forged = p2p.ledger.put("PrivateNote", {"owner": "triad", "work_item_id": a.work_item_id, "status": "PRIVATE_GRAPH_MARKER"})
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        # Even a bad historical edge must not expose the foreign record.
        session.run("MATCH (a:WorkItem {id:$a}), (b:JournalEntry {id:$b}) MERGE (a)-[:SUPPORTED_BY]->(b)", a=a.work_item_id, b=journal.journal_id).consume()
        assert session.run("MATCH (n {id:$id}) RETURN n.owner AS owner", id=forged).single()["owner"] == "p2p"
    lineage = graph.lineage(a.work_item_id)
    assert journal.journal_id not in {row['id'] for row in lineage}
    assert forged not in {row['id'] for row in lineage}
    assert 'triad:' + a.mission_id in {row['id'] for row in lineage}
    with pytest.raises(PermissionError):
        graph.lineage(b.work_item_id)
    assert journal.journal_id in {row['id'] for row in Brain(p2p.host.store).lineage(b.work_item_id)}
