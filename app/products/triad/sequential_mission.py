"""Operator mission and evidence-labelled progress, outside autonomous page content."""

import json
import logging
import re
from html import escape
from importlib.resources import files


def mission_statement():
    return json.loads(
        files("products.triad").joinpath("resources/product.json").read_text(encoding="utf-8")
    )["mission"]


def progress():
    from trading_core.store import Store

    # Read only Triad evidence, with explicit ownership even on the scoped connection.
    # Project only the small display fields; cycle snapshots contain large transcripts.
    with Store(scope="triad").connect() as conn:
        cycle = conn.execute(
            "SELECT payload->>'cycle_id' AS id, payload->>'status' AS status "
            "FROM core.intelligence_records WHERE owner='triad' AND kind='CycleRecord' "
            "ORDER BY created_at DESC,id DESC LIMIT 1"
        ).fetchone()
        if not cycle:
            return None
        proposals = conn.execute(
            "SELECT DISTINCT ON (payload->>'proposer') payload->>'proposer' AS agent, "
            "payload->'proposal'->>'title' AS title, payload->'proposal'->'value_plan' AS plan "
            "FROM core.intelligence_records WHERE owner='triad' AND kind='ProductProposal' "
            "AND payload->>'mission_id'=%s "
            "ORDER BY payload->>'proposer',created_at DESC,id DESC",
            (cycle["id"],),
        ).fetchall()
        turns = conn.execute(
            "SELECT DISTINCT ON (payload->>'agent') payload->>'agent' AS agent, "
            "CASE WHEN payload->>'outcome'='NO_CHANGE' THEN 'Reviewed no-change; nothing deployed' "
            "ELSE payload->>'status' END AS status FROM core.intelligence_records "
            "WHERE owner='triad' AND kind='ProductTurn' AND payload->>'mission_id'=%s "
            "ORDER BY payload->>'agent',created_at DESC,id DESC",
            (cycle["id"],),
        ).fetchall()
    return {**cycle, "proposals": proposals, "turns": {r["agent"]: r["status"] for r in turns}}


def render_panel(mission, state=None, *, unavailable=False):
    def text(value):
        return escape(str(value))

    parts = [
        '<section id="triad-mission" aria-labelledby="mission-heading">',
        '<h2 id="mission-heading">Our mission</h2>',
    ]
    parts.extend("<p>" + text(p) + "</p>" for p in mission.split("\n\n"))
    parts.append("<details><summary>Current initiatives and latest cycle contributions</summary>")
    if unavailable:
        parts.append("<p>Progress is temporarily unavailable. The mission remains unchanged.</p>")
    elif not state:
        parts.append("<p>No cycle evidence is recorded yet.</p>")
    else:
        parts.append(
            "<p>Latest cycle: "
            + text(state["id"])
            + " — "
            + text(state["status"])
            + ". Plans below are agent assessments. Completed changes and reviewed no-change turns are distinguished below.</p>"
        )
        proposals = {r["agent"]: r for r in state["proposals"]}
        for agent in ("CODEX", "CLAUDE", "GROK"):
            row = proposals.get(agent)
            parts.append("<h3>" + agent.title() + "</h3>")
            if not row:
                parts.append("<p>No proposal recorded for this cycle yet.</p>")
                continue
            plan = row.get("plan") or {}
            status = state["turns"].get(agent, "Proposed; delivery not verified")
            parts.append(
                "<p><strong>" + text(status) + "</strong> · " + text(row["title"]) + "</p>"
            )
            for label, key in (
                ("Initiative", "initiative"),
                ("User outcome", "user_outcome"),
                ("Contribution to the mission", "mission_contribution"),
            ):
                if plan.get(key):
                    parts.append("<p><strong>" + label + ":</strong> " + text(plan[key]) + "</p>")
            parts.append("<h4>Major remaining gaps — agent assessment</h4>")
            gaps = plan.get("major_gaps")
            parts.append(
                "<ul>" + "".join("<li>" + text(g) + "</li>" for g in gaps) + "</ul>"
                if gaps
                else "<p>Not assessed in this historical plan.</p>"
            )
            if plan.get("next_steps"):
                parts.append(
                    "<p><strong>Next steps:</strong> "
                    + text("; ".join(plan["next_steps"]))
                    + "</p>"
                )
        parts.append(
            '<p><a href="/triad/cycles">Cycle evidence</a> · '
            '<a href="/triad/daily-debrief">Reviewed daily debrief</a></p>'
        )
    parts.append("</details></section>")
    return "".join(parts)


def mission_panel():
    mission = mission_statement()
    try:
        return render_panel(mission, progress())
    except Exception:  # Read-only progress must not take down the product page.
        logging.getLogger(__name__).warning("Mission progress unavailable", exc_info=True)
        return render_panel(mission, unavailable=True)


def insert_panel(source, panel):
    # Product developers may change the page layout without dropping the mission.
    for tag in ("main", "body"):
        pattern = r"<" + tag + r"\b[^>]*>"
        if re.search(pattern, source, re.IGNORECASE):
            return re.sub(pattern, lambda m: m[0] + panel, source, count=1, flags=re.IGNORECASE)
    return panel + source
