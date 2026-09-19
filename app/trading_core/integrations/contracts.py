"""Provider-neutral contracts; metadata never contains credentials."""

from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from trading_core.work import Record, now, uid

CATEGORIES = (
    "BROKER",
    "MARKET_DATA",
    "HISTORICAL_DATA",
    "FUNDAMENTALS",
    "NEWS",
    "SENTIMENT",
    "ECONOMIC_DATA",
    "ALTERNATIVE_DATA",
    "EXECUTION_VENUE",
    "OTHER",
)
CapabilityState = Literal["IMPLEMENTED", "UNVERIFIED", "UNAVAILABLE", "NOT_CONFIGURED"]
CandidateStatus = Literal[
    "DISCOVERED",
    "RESEARCHING",
    "APPROVED_FOR_IMPLEMENTATION",
    "REJECTED",
    "IMPLEMENTED",
    "DEPRECATED",
]


class IntegrationRecord(Record):
    integration_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    name: str
    provider: str
    category: str = Field(pattern=r"^[A-Z][A-Z_]{1,49}$")
    status: str = "NOT_CONFIGURED"
    capabilities: dict[str, CapabilityState]
    authentication_type: str
    configured: bool = False
    connected: bool = False
    enabled: bool = False
    environment: str = "UNCONFIGURED"
    endpoint: HttpUrl | None = None
    documentation_reference: tuple[HttpUrl, ...] = ()
    rate_limits: dict = Field(default_factory=dict)
    data_limits: dict = Field(default_factory=dict)
    cost_model: str = "UNKNOWN"
    permissions_required: tuple[str, ...] = ()
    created_at: AwareDatetime = Field(default_factory=now)
    updated_at: AwareDatetime = Field(default_factory=now)
    last_health_check: AwareDatetime | None = None
    last_success: AwareDatetime | None = None
    last_failure: AwareDatetime | None = None
    notes: tuple[str, ...] = ()
    transports: tuple[dict, ...] = ()


class IntegrationConnection(Record):
    connection_id: str = Field(default_factory=uid)
    integration_id: str
    status: str
    connected: bool
    created_at: AwareDatetime = Field(default_factory=now)
    checked_at: AwareDatetime = Field(default_factory=now)
    last_success: AwareDatetime | None = None
    last_failure: AwareDatetime | None = None
    detail: str


class IntegrationCandidate(Record):
    candidate_id: str = Field(default_factory=uid)
    provider: str = Field(min_length=1, max_length=160)
    category: str = Field(pattern=r"^[A-Z][A-Z_]{1,49}$")
    proposed_by: str
    reason: str = Field(min_length=1, max_length=4000)
    capabilities: tuple[str, ...]
    documentation: tuple[HttpUrl, ...]
    cost: str = Field(max_length=1000)
    limitations: tuple[str, ...]
    security_review: str = "PENDING"
    status: CandidateStatus = "DISCOVERED"
    created_at: AwareDatetime = Field(default_factory=now)
    updated_at: AwareDatetime = Field(default_factory=now)


class DataRequest(Record):
    request_id: str = Field(default_factory=uid)
    symbols: tuple[str, ...] = Field(min_length=1, max_length=20)
    asset_class: Literal["equity"] = "equity"
    resolution: Literal["1m"] = "1m"
    start: AwareDatetime
    end: AwareDatetime
    volume_required: bool = True
    mode: Literal["REAL", "FIXTURE"] = "REAL"
    license_use: str = "research"
    max_cost_usd: float = Field(default=0, ge=0)
    requested_at: AwareDatetime = Field(default_factory=now)

    @model_validator(mode="after")
    def bounded(self):
        if self.end <= self.start or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Require distinct symbols and nonempty time interval")
        return self
