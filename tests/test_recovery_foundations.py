from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest
from trading_core.intelligence.contracts import QARun
from trading_core.intelligence.quality import Quality
from trading_core.providers.codex_executor import observe_completed_read

pytestmark = pytest.mark.core


@pytest.mark.parametrize(
    "command",
    [
        "cat evidence/a.txt",
        "cat -- /workspace/evidence/a.txt",
        "/usr/bin/bash -lc 'cat evidence/a.txt'",
    ],
)
def test_authorized_completed_read_supplies_deduplicatable_progress(command):
    calls = []
    executor = NS(
        files={"evidence/a.txt": "actual bytes"},
        requests=[{"params": {"argv": ["cat", "--", "evidence/a.txt"]}}],
    )
    resources = NS(observe=lambda *a: calls.append(a))
    observe_completed_read(executor, command, resources)
    observe_completed_read(executor, command, resources)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0][0] == "authorized_read"
    assert calls[0][1].startswith("evidence/a.txt:")


@pytest.mark.parametrize(
    "command",
    [
        "cat private.txt",
        "cat evidence/a.txt; echo done",
        "echo evidence/a.txt",
        "cat 'bad",
        "cat evidence/a.txt evidence/b.txt",
        None,
    ],
)
def test_claims_unobserved_reads_and_shell_composition_cannot_supply_progress(command):
    executor = NS(
        files={"evidence/a.txt": "actual bytes", "evidence/b.txt": "other"},
        requests=[{"params": {"argv": ["cat", "--", "evidence/a.txt"]}}],
    )

    def forbidden(*a):
        pytest.fail("Unobserved command counted as progress")

    observe_completed_read(executor, command, NS(observe=forbidden))


def test_positive_review_findings_are_not_debt_and_explicit_followup_is_retained():
    rows = []
    records = NS(
        store=NS(scope=None, connect=lambda: nullcontext(None)),
        get=lambda _: {
            "kind": "ImplementationRun",
            "builder": "CODEX",
            "change_commit": "commit",
            "owner": "triad",
        },
    )

    def append(kind, payload, **kwargs):
        rows.append((kind, payload))
        return str(len(rows))

    records.append = append
    qa = QARun(
        implementation_run_id="impl",
        qa_agent="CLAUDE",
        qa_provider="anthropic",
        qa_model="fixture",
        reviewed_commit="commit",
        agent_capabilities_used=("source_review",),
        findings=("Protected paths unchanged",),
        optional_improvements=("Add browser verification",),
        tests_repeated=("Source checked",),
        evidence=("fixture",),
        decision="PASS_WITH_OBSERVATIONS",
        execution_mode="TEST_FIXTURE",
    )
    Quality(records).review(qa)
    assert rows[0][1]["findings"] == ["Protected paths unchanged"]
    assert [(kind, row.get("finding")) for kind, row in rows if kind == "QualityDebt"] == [
        ("QualityDebt", "Add browser verification")
    ]
