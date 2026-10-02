"""A reviewer may correct omitted citations; host evidence never becomes a verdict."""

from trading_core.product_changes import AcceptanceAssessment, acceptance_problems


def citation_omission(required, assessment, commit, proofs, decision):
    """Only an approving, complete assessment with successful exact tests qualifies."""
    if decision != "APPROVE" or len(proofs) != 2:
        return False
    assessment = AcceptanceAssessment.model_validate(assessment)
    if not acceptance_problems(required, assessment, commit, proofs):
        return False
    source = "candidate:" + commit
    expected = {c["check_id"]: c for c in required}
    if len(expected) != len(required) or len(assessment.checks) != len(expected):
        return False
    if {c.check_id for c in assessment.checks} != set(expected):
        return False
    if any(
        p.get("kind") != "EngineeringTestRun"
        or p.get("owner") != "triad"
        or p.get("commit") != commit
        or p.get("status") != "PASS"
        or p.get("test_status") != "PASSED"
        or p.get("executed_tests", 0) < 1
        for p in proofs.values()
    ):
        return False
    for check in assessment.checks:
        refs = set()
        for value in check.evidence_ids:
            prefix, _, identifier = value.partition(":")
            refs.add(
                identifier
                if prefix in {"test_record_id", "repeated_test_record_id"} and identifier in proofs
                else value
            )
        if check.status != "VERIFIED" or not refs or not refs <= {source, *proofs}:
            return False
        if expected[check.check_id]["method"] == "SOURCE_REVIEW" and source not in refs:
            return False
    return True


def accepted_correction(original, updated, required, commit, proofs):
    """Citation-only means every substantive criterion remains byte-for-byte intact."""
    original = {c.check_id: c for c in original.checks}
    return (
        len(updated.checks) == len(original)
        and {c.check_id for c in updated.checks} == set(original)
        and all(
            c.status == original[c.check_id].status and c.reason == original[c.check_id].reason
            for c in updated.checks
        )
        and not acceptance_problems(required, updated, commit, proofs)
    )


def retain_findings(original, corrected):
    """Keep all original observations plus the correction's summary, with provenance."""
    return corrected.model_copy(
        update={"findings": tuple(dict.fromkeys((*original.findings, *corrected.findings)))}
    )


def correct_citations(flow, mission, agent, proposal, build, completed, proofs):
    """One small, read-only follow-up to the same reviewer; retain both responses."""
    from products.triad.sequential import REVIEWERS

    work, result, assessment, usage = completed
    required = [c.model_dump(mode="json") for c in proposal.acceptance]
    commit = build["git"]["change_commit"]
    if not citation_omission(required, assessment, commit, proofs, result.review_decision):
        return completed
    flow.s.record(
        "ProductCitationCorrectionRequested",
        mission,
        implementation_id=build["implementation_id"],
        commit=commit,
        reviewer=REVIEWERS[agent],
        original_work_item_id=work.work_item_id,
        original_result=result.model_dump(mode="json"),
        usage=usage,
        original_assessment=assessment.model_dump(mode="json"),
        test_record_ids=list(proofs),
    )
    corrected = flow.call(
        mission,
        REVIEWERS[agent],
        "Correct omitted test citations in your supplied independent assessment of this exact candidate. "
        "Read both canonical test records. Each PYTHON_UNIT_TEST check must cite BOTH raw test IDs. "
        "Copy check IDs, statuses and reason strings exactly; preserve all original findings; do not invent evidence or repeat development. "
        "If the supplied evidence does not support your previous conclusion, return REQUEST_CHANGES or REJECT. "
        "Return one complete AcceptanceAssessment and review_decision/findings. This is a citation correction, "
        "not a new source inspection; the host will revalidate every acceptance check.",
        {
            "exact_commit": commit,
            "required": required,
            "original_assessment": assessment.model_dump(mode="json"),
            "original_findings": list(result.findings),
            "previous_run_id": usage["run_id"],
            "test_records": proofs,
            "allowed_evidence_ids": ["candidate:" + commit, *proofs],
            "schema": AcceptanceAssessment.model_json_schema(),
        },
        AcceptanceAssessment,
    )
    _, response, updated, new_usage = corrected
    accepted = accepted_correction(assessment, updated, required, commit, proofs)
    flow.s.record(
        "ProductCitationCorrectionResult",
        mission,
        implementation_id=build["implementation_id"],
        commit=commit,
        previous_run_id=usage["run_id"],
        run_id=new_usage["run_id"],
        usage=new_usage,
        assessment=updated.model_dump(mode="json"),
        review_decision=response.review_decision,
        accepted=accepted and response.review_decision == "APPROVE",
    )
    if response.review_decision != "APPROVE":
        return corrected  # A refusal always reaches the ordinary failure gate.
    if accepted:
        return corrected[0], retain_findings(result, response), updated, new_usage
    return completed
