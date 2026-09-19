"""Configuration and observed evidence, never inferred model-quality claims."""

from trading_core.runtime import ProviderError

from products.triad.cycles import Cycles


def readiness(cycles=None, probe=False):
    cycles = cycles or Cycles()
    control = cycles.ledger.control()
    health = cycles.runtime.health() if probe else cycles.ledger.records("ProviderHealth")
    usage = cycles.ledger.records("Usage", 1000)
    providers = []
    for agent in (*cycles.rotation, "LOCAL_QWEN"):
        adapter = cycles.runtime.provider(agent, "REAL")
        observed = next((h for h in health if h["agent"] == agent), {})
        reasons = []
        if observed.get("status") != "AVAILABLE":
            reasons.append(observed.get("error_class") or "HEALTH_NOT_AVAILABLE")
        if agent in control["disabled_agents"]:
            reasons.append("AGENT_DISABLED")
        try:
            estimate = adapter.estimate_cost(8000, 1024)
        except ProviderError:
            estimate = None
            reasons.append("PRICING_NOT_CONFIGURED")
        billing = adapter.billing_source() if hasattr(adapter, "billing_source") else "UNKNOWN"
        if billing == "API" and control["limits"]["max_cloud_cost_day"] <= 0:
            reasons.append("CLOUD_BUDGET_NOT_AUTHORIZED")
        if control["paused"] or control["killed"]:
            reasons.append("CONTROL_PAUSED")
        successes = [
            u
            for u in usage
            if u["agent"] == agent and u["mode"] == "REAL" and u["status"] == "SUCCESS"
        ]
        providers.append(
            {
                "agent": agent,
                "provider": adapter.provider,
                "model": adapter.model or "not_configured",
                "health": observed.get("status", "NOT_CHECKED"),
                "checked_at": observed.get("checked_at"),
                "configuration_ready": not reasons,
                "blockers": reasons,
                "illustrative_8000_input_1024_output_usd": estimate if billing == "API" else None,
                "billing_source": billing,
                "observed_real_successes": len(successes),
                "last_real_run": successes[0]["run_id"] if successes else None,
                "quality": "NOT_EVALUATED",
                "scope": "Bounded retained history; readiness does not reserve budget or authorize execution",
            }
        )
    reviews = cycles.ledger.records("AutonomousReview", 1000)
    metrics = []
    for mode in ("REAL", "SIMULATED"):
        selected = [r for r in reviews if r["execution_mode"] == mode]
        metrics.append(
            {
                "mode": mode,
                "reviews": len(selected),
                "approved": sum(r["decision"] == "APPROVE" for r in selected),
                "rejected_or_changes": sum(r["decision"] != "APPROVE" for r in selected),
                "distinct_reviewer": sum(r["reviewer"] != r["worker"] for r in selected),
                "with_repeated_checks": sum(bool(r["tests_repeated"]) for r in selected),
                "with_evidence": sum(bool(r["evidence_checked"]) for r in selected),
                "correctness": "NOT_MEASURED: approval is not a quality score; human-labelled evaluation required",
            }
        )
    return {
        "providers": providers,
        "review_evidence": metrics,
        "cloud_validation": "BLOCKED"
        if any(p["blockers"] for p in providers[:3])
        else "READY_FOR_AUTHORIZED_BOUNDED_TEST",
    }
