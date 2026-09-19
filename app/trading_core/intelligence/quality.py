"""Host-ingested independent QA, revision-bound acceptance and retained quality debt.

No model-facing or unauthenticated API can submit a passing verdict. Host callers
must preserve the independent run transcript/test evidence they actually observed.
"""

from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.records import Records


class Quality:
    def __init__(self, records=None):
        self.records = records or Records()

    def implementation(self, run: ImplementationRun):
        return self.records.append(
            "ImplementationRun",
            run.model_dump(mode="json"),
            owner=run.owner,
            identifier=run.implementation_run_id,
        )

    def review(self, qa: QARun):
        if self.records.store.scope is not None:
            raise PermissionError("QA verdict ingestion is a trusted Core host operation")
        build = self.records.get(qa.implementation_run_id)
        if build["kind"] != "ImplementationRun" or build["builder"] == qa.qa_agent:
            raise PermissionError("A separate QA identity must review an implementation")
        if build["change_commit"] != qa.reviewed_commit:
            raise PermissionError("QA is stale for this implementation")
        with self.records.store.connect() as conn:
            identifier = self.records.append(
                "QARun",
                qa.model_dump(mode="json"),
                owner=build["owner"],
                identifier=qa.qa_run_id,
                conn=conn,
            )
            observations = tuple(
                dict.fromkeys(
                    (*qa.findings, *qa.optional_improvements)
                    if qa.decision == "PASS_WITH_OBSERVATIONS"
                    else qa.optional_improvements
                )
            )
            for finding in observations:
                self.records.append(
                    "QualityDebt",
                    {
                        "source_qa_run": identifier,
                        "finding": finding,
                        "severity": "LOW",
                        "product_area": build["owner"],
                        "reason_deferred": "Independent QA classified as non-blocking",
                        "status": "OPEN",
                    },
                    owner=build["owner"],
                    conn=conn,
                )
        return identifier

    def require_pass(self, implementation_id, commit, *, conn=None):
        build = self.records.get(implementation_id, conn=conn)
        # Revalidate even host-ingested evidence before it can authorize a merge.
        ImplementationRun.model_validate(
            {k: v for k, v in build.items() if k in ImplementationRun.model_fields}
        )
        reviews = [
            r
            for r in self.records.list("QARun", conn=conn)
            if r["implementation_run_id"] == implementation_id
        ]
        if (
            build["kind"] != "ImplementationRun"
            or build["status"] != "IMPLEMENTED"
            or build["change_commit"] != commit
            or not reviews
        ):
            raise PermissionError("Current implementation requires independent QA")
        qa = reviews[-1]
        QARun.model_validate({k: v for k, v in qa.items() if k in QARun.model_fields})
        if (
            qa["reviewed_commit"] != commit
            or qa["decision"] not in {"PASS", "PASS_WITH_OBSERVATIONS"}
            or qa["qa_agent"] == build["builder"]
            or qa["execution_mode"] == "TEST_FIXTURE"
        ):
            raise PermissionError("Latest independent QA did not pass this revision")
        return qa
