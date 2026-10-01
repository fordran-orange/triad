"""Generic immutable cycle evidence; products supply their own orchestration."""

from typing import Literal

from pydantic import AwareDatetime, Field

from trading_core.work import Record, now


class CycleRecord(Record):
    cycle_id: str
    product: Literal["triad", "aegis"]
    cycle_type: str
    execution_mode: Literal["REAL", "SIMULATED", "UNKNOWN"]
    status: str
    created_at: AwareDatetime | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    recorded_at: AwareDatetime = Field(default_factory=now)
    control_epoch: int | None = None
    scheduled: bool | None = None
    parent_work_item_id: str | None = None
    agents_run: tuple[str, ...] = ()
    work_items: tuple[dict, ...] = ()
    provider_runs: tuple[dict, ...] = ()
    candidate_improvements: tuple[dict, ...] = ()
    proposals: tuple[dict, ...] = ()
    selected_proposal: dict | None = None
    implementation_runs: tuple[dict, ...] = ()
    qa_runs: tuple[dict, ...] = ()
    correction_runs: tuple[dict, ...] = ()
    reviews: tuple[dict, ...] = ()
    disagreements: tuple[dict, ...] = ()
    changes_accepted: tuple[str, ...] = ()
    changes_rejected: tuple[str, ...] = ()
    changes_rolled_back: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    failures: tuple[dict, ...] = ()
    lessons: tuple[str, ...] = ()
    quality_debt: tuple[dict, ...] = ()
    billing_sources: tuple[str, ...] = ()
    api_cost: float | None = None
    subscription_usage: tuple[dict, ...] = ()
    local_usage: tuple[dict, ...] = ()
    merge_commit: str | None = None
    verified_revision: str | None = None
    product_state_before: dict = Field(default_factory=dict)
    product_state_after: dict = Field(default_factory=dict)
    next_cycle_candidates: tuple[str, ...] = ()
    failure_code: str | None = None
    blocked_at: AwareDatetime | None = None
    provider_gate_result: dict | None = None
    recovery_action: str | None = None
    superseded_by_cycle_id: str | None = None
    recovered_by_cycle_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    provenance_notes: tuple[str, ...] = ()
