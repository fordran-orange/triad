"""Strategy documents (Mission 5 spec §8): named, saved strategy specs.

A document's id is its spec's `id` and its name is the spec's `name` (plan ruling P1), so every
persisted run, optimization and walk-forward, including those written before Mission 5, already
names the document it used through `strategy.id`. The built-in reference strategy is
synthesized from `default_strategy()` on every read and is never written (P10). Deleting a
document is refused while anything persisted references it, running jobs included.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from products.aegis.results import strategy_hash
from products.aegis.runs import RunRepository
from products.aegis.strategy import StrategySpec, default_strategy

BUILTIN_ID = "ema9-sma30-cross-v1"
USAGE_KINDS = ("runs", "optimizations", "walkforwards")


class StrategyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = Field(min_length=1, max_length=120)
    spec: StrategySpec
    created_at: str | None
    updated_at: str | None
    strategy_hash: str
    parent: str | None = None
    builtin: bool = False


class BuiltinRefused(ValueError):
    def __init__(self) -> None:
        super().__init__("the built-in strategy is read-only; duplicate it")


class StrategyReferenced(Exception):
    def __init__(self, identifier: str, counts: dict[str, int]) -> None:
        self.counts = counts
        names = {"runs": "run", "optimizations": "optimization", "walkforwards": "walk-forward"}
        parts = [
            f"{counts[kind]} {names[kind]}{'' if counts[kind] == 1 else 's'}"
            for kind in USAGE_KINDS
        ]
        super().__init__(f"strategy {identifier} is referenced by {', '.join(parts)}")


def slug(name: str) -> str:
    """Lowercase, runs of anything but a-z0-9 become one dash, at most 48 characters."""
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return text or "strategy"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _strategy_id(summary: dict) -> str | None:
    """The strategy a persisted envelope used: its own field, or (before Mission 5) strategy.id."""
    return summary.get("strategy_id") or (summary.get("strategy") or {}).get("id")


def _kinds(spec: dict) -> list[str]:
    return sorted(
        {
            str(indicator.get("kind", "")).upper()
            for side in ("long_side", "short_side")
            for indicator in (spec.get(side) or {}).get("indicators", [])
        }
    )


class StrategyLibrary:
    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    # -- reads ------------------------------------------------------------------------------
    def _builtin(self) -> StrategyDocument:
        spec = default_strategy()
        return StrategyDocument(
            id=BUILTIN_ID,
            name=spec.name,
            spec=spec,
            created_at=None,
            updated_at=None,
            strategy_hash=strategy_hash(spec),
            builtin=True,
        )

    def get(self, identifier: str) -> StrategyDocument:
        """The document, or KeyError when unknown. A saved document that no longer parses raises
        pydantic's ValidationError (a ValueError) for the caller to report (P14 item 2)."""
        if identifier == BUILTIN_ID:
            return self._builtin()
        return StrategyDocument.model_validate(self._raw(identifier))

    def _raw(self, identifier: str) -> dict:
        try:
            return self.repository.get_strategy(identifier)
        except ValueError as exc:  # an identifier the repository refuses is simply unknown
            raise KeyError(identifier) from exc

    def _usage_counters(self) -> dict[str, Counter]:
        return {
            "runs": Counter(_strategy_id(s) for s in self.repository.list_runs()),
            "optimizations": Counter(_strategy_id(s) for s in self.repository.list_optimizations()),
            "walkforwards": Counter(_strategy_id(s) for s in self.repository.list_walkforwards()),
        }

    def usage(self, identifier: str) -> dict[str, int]:
        counters = self._usage_counters()
        return {kind: counters[kind][identifier] for kind in USAGE_KINDS}

    def list(self) -> list[dict]:
        counters = self._usage_counters()
        builtin = self._builtin()
        items = [
            {
                **builtin.model_dump(mode="json", exclude={"spec"}),
                "kinds": _kinds(builtin.spec.model_dump(mode="json")),
            }
        ]
        saved = sorted(
            self.repository.list_strategies(),
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )
        items += [item for item in saved if item.get("id") != BUILTIN_ID]
        return [
            {**item, "usage": {kind: counters[kind][item["id"]] for kind in USAGE_KINDS}}
            for item in items
        ]

    # -- writes -----------------------------------------------------------------------------
    def _free_id(self, name: str) -> str:
        base = slug(name)
        taken = {item.get("id") for item in self.repository.list_strategies()} | {BUILTIN_ID}
        if base not in taken:
            return base
        suffix = hashlib.sha256(f"{name}|{_now()}".encode()).hexdigest()
        candidate = f"{base}-{suffix[:6]}"
        while candidate in taken:
            suffix = hashlib.sha256(suffix.encode()).hexdigest()
            candidate = f"{base}-{suffix[:6]}"
        return candidate

    def _save(
        self,
        identifier: str,
        name: str,
        spec: StrategySpec,
        created_at: str,
        updated_at: str,
        parent: str | None,
    ) -> StrategyDocument:
        named = StrategySpec.model_validate(
            {**spec.model_dump(mode="json"), "id": identifier, "name": name}
        )
        document = StrategyDocument(
            id=identifier,
            name=name,
            spec=named,
            created_at=created_at,
            updated_at=updated_at,
            strategy_hash=strategy_hash(named),
            parent=parent,
        )
        self.repository.save_strategy(document.model_dump(mode="json"))
        return document

    def create(self, name: str, spec: StrategySpec, parent: str | None = None) -> StrategyDocument:
        now = _now()
        return self._save(self._free_id(name), name, spec, now, now, parent)

    def update(
        self, identifier: str, name: str | None = None, spec: StrategySpec | None = None
    ) -> StrategyDocument:
        if identifier == BUILTIN_ID:
            raise BuiltinRefused()
        current = self.get(identifier)
        now = max(_now(), current.updated_at or "")
        return self._save(
            identifier,
            name if name is not None else current.name,
            spec if spec is not None else current.spec,
            current.created_at or now,
            now,
            current.parent,
        )

    def duplicate(self, identifier: str, name: str) -> StrategyDocument:
        source = self.get(identifier)
        return self.create(name, source.spec, parent=identifier)

    def delete(self, identifier: str) -> None:
        if identifier == BUILTIN_ID:
            raise BuiltinRefused()
        self._raw(identifier)  # KeyError when unknown; a document that no longer parses may go
        counts = self.usage(identifier)
        if any(counts.values()):
            raise StrategyReferenced(identifier, counts)
        self.repository.delete_strategy(identifier)


__all__ = [
    "BUILTIN_ID",
    "BuiltinRefused",
    "StrategyDocument",
    "StrategyLibrary",
    "StrategyReferenced",
    "slug",
]
