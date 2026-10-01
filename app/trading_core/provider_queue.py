"""Wait for an existing provider run without replaying work or bypassing stop controls."""

import time
from contextlib import ExitStack, contextmanager

from trading_core.store import ConcurrentUpdate


@contextmanager
def provider_slot(ledger, request):
    while True:
        ledger.guard(request.agent_id, request.work_item_id, request.control_epoch)
        with ExitStack() as stack:
            try:
                stack.enter_context(ledger.store.lease("provider-execution-" + request.agent_id))
            except ConcurrentUpdate:
                pass
            else:
                # Exceptions in an already started run must escape, never trigger a retry.
                ledger.guard(request.agent_id, request.work_item_id, request.control_epoch)
                yield
                return
        time.sleep(1)
