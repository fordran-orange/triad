"""Wake the local worker without polling idle queues every ten seconds."""

from datetime import UTC, datetime
from threading import Event

WAKE = Event()
QUEUE_WAKE = Event()
IDLE_SECONDS = 300
ACTIVE_SECONDS = 30


def wake():
    WAKE.set()
    QUEUE_WAKE.set()


def notify(store):
    """Durable queue remains authoritative; notification contains no content."""
    wake()
    try:
        with store.connect() as conn:
            conn.execute("SELECT pg_notify('triad_worker_wake','')")
    except Exception:  # noqa: BLE001 - notification cannot invalidate durable submission
        # Submission is already durable. A notification outage must not turn
        # an accepted submission into a reported failure and duplicate retry.
        import logging

        logging.getLogger(__name__).warning(
            "Worker notification unavailable; polling remains active"
        )


def listen(stop):
    from trading_core.store import Store

    while not stop.is_set():
        try:
            with Store().connect() as conn:
                conn.autocommit = True
                conn.execute("LISTEN triad_worker_wake")
                while not stop.is_set():
                    for _ in conn.notifies(timeout=2, stop_after=1):
                        wake()
        except Exception:  # noqa: BLE001 - reconnectable notification listener
            stop.wait(30)  # Poll fallback remains available if notifications fail.


def delay(service, instant=None):
    from products.triad.daily_scheduler import next_cycle

    instant = instant or datetime.now(UTC)
    target = next_cycle(service.schedule(), instant)
    wait = IDLE_SECONDS
    if target:
        wait = min(wait, max(0.1, (datetime.fromisoformat(target) - instant).total_seconds()))
    # Small fields only. Never repeatedly fetch large provider transcripts.
    with service.host.store.connect() as conn:
        pending = conn.execute(
            "SELECT 1 FROM core.intelligence_records d WHERE d.owner='triad' AND d.kind='DailyDispatch' "
            "AND COALESCE((SELECT c.payload->>'status' FROM core.intelligence_records c "
            "WHERE c.owner='triad' AND c.kind='CycleRecord' AND c.payload->>'cycle_id'=d.payload->>'cycle_id' "
            "ORDER BY c.created_at DESC,c.id DESC LIMIT 1),'PENDING') "
            "NOT IN ('COMPLETED','BLOCKED','FAILED','CANCELLED') LIMIT 1"
        ).fetchone()
    return min(wait, ACTIVE_SECONDS) if pending else wait
