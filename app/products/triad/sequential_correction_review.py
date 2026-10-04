"""Review the current correction, without re-running product feature selection."""

CORRECTION_REVIEW_OBJECTIVE = (
    "You are the independent PROPOSAL_REVIEWER of current_correction_plan. "
    "The original feature, file manifest and acceptance contract are immutable. "
    "Decide whether this current plan credibly closes the supplied independent QA gaps "
    "on the current baseline. This is permission to implement a correction, not a QA pass. "
    "Fresh implementation, repeated tests and independent candidate QA remain mandatory. "
    "Evaluate current_correction_plan.steps, not descriptions of rejected earlier methods "
    "in its summary, historical feedback or retained source. A mention of a prior rejected "
    "method does not propose using it. Accept a functionally equivalent concrete approach; "
    "do not require verbatim keywords or a complete executable test in a planning artifact. "
    "For each REQUEST_CHANGES finding, identify the original check_id, quote the exact "
    "current step text that is inadequate, and explain the behavioral gap and concrete "
    "required correction. Distinguish a genuine new gap from a repeated wording preference. "
    "Explicitly identify steps already adequate and preserve their approach; do not reopen "
    "verified QA checks or choose a new feature. Return APPROVE only if every remaining "
    "obligation has a credible approach, otherwise REQUEST_CHANGES, REJECT or BLOCKED "
    "with grounded findings. No code execution, new authority or invented test results."
)


def correction_context(agent, reviewer, proposal, retained, plan, baseline, feedback, sources):
    """Keep exact authority/provenance and candidate bytes; omit unrelated inventory."""
    if retained is None:
        raise PermissionError("A correction review requires its retained unmerged candidate")
    candidate = {
        k: v for k, v in retained.items() if k not in {"author_correction_plan", "renewal_feedback"}
    }
    latest = feedback[-1] if feedback else retained.get("renewal_feedback")
    return {
        "task_assignment": {
            "phase": "PROPOSAL_REVIEWER",
            "author": agent,
            "independent_reviewer": reviewer,
            "execution_role": "REVIEW",
            "execution_role_meaning": "Read-only independent review of the current correction plan",
        },
        "correction_review_version": "current-obligations-v1",
        "proposal": proposal.model_dump(mode="json"),
        "base_commit": baseline,
        # These canonical fields are still checked against actual closed runs.
        "retained_unmerged_candidate": candidate,
        "correction_plan": plan,
        "current_correction_plan": plan["plan"],
        "latest_requested_changes": latest,
        "historical_context_notice": (
            "Retained code and QA describe the unmerged candidate before correction. "
            "Latest requested changes describe the prior plan, not the current plan. "
            "Judge whether current_correction_plan resolves those obligations."
        ),
        "current_baseline_approved_files": sources,
    }
