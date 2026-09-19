"""Future reviewed knowledge transfer contract. No imports are enabled."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExchangeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_product: Literal["triad", "p2p"]
    destination_product: Literal["triad", "p2p"]
    record_ids: tuple[str, ...]
    status: Literal["CLOSED"] = "CLOSED"


def import_candidate(candidate: ExchangeCandidate):
    raise PermissionError("Cross-product exchange is closed; no import capability is granted")
