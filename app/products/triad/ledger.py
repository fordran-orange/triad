"""Triad's daily improvement policy, layered on Core's global budget."""

from trading_core.ledger import Ledger


class ProductLedger(Ledger):
    def reserve_product(self, conn, agent, work_id, day, improvement):
        if not improvement:
            return
        if conn.execute(
            "SELECT 1 FROM triad.improvement_slots WHERE day=%s AND agent=%s", (day, agent)
        ).fetchone():
            raise PermissionError("Daily agent improvement slot already consumed")
        conn.execute("INSERT INTO triad.improvement_slots VALUES (%s,%s,%s)", (day, agent, work_id))
