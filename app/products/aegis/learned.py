"""Learned phrases and accepted examples (Mission 14 spec §4.3).

When the operator applies a reading the AI made, the example is always kept, and each substitution
the AI listed becomes a learned phrase only when it is context-free:

1. its `from` words are in the text (whole words) and its `to` is words the reader knows;
2. its `from` brings at least one word the reader does not know, so a learned phrase can never
   change a sentence the reader already understood;
3. its `to` brings no operand (indicator, output, price word or number) its `from` lacks, so a
   reading tied to one sentence ("it" -> "9 ema") is not learned;
4. the AI's substitutions, all applied to the text, give exactly the sides of its rewrite: they
   really explain it. Otherwise nothing is learned from that reading.

Files, beside the saved runs: `phrases/learned.json` and `phrases/examples.jsonl`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from products.aegis.phrases import (
    KIND_WORDS,
    KNOWN_WORDS,
    OUTPUT_WORDS,
    PRICE_WORDS,
    TOKEN,
    Unread,
    apply_learned,
    read,
)
from products.aegis.runs import _retry
from products.aegis.strategy import StrategySpec

EXAMPLES_IN_PROMPT = 20
OPERANDS = set(KIND_WORDS) | OUTPUT_WORDS | set(PRICE_WORDS)
NUMBER = re.compile(r"\d+(\.\d+)?%?")
_LOCK = threading.Lock()


def _words(text: str) -> list[str]:
    return text.lower().split()


def _operands(text: str) -> set[str]:
    return {w for w in _words(text) if w in OPERANDS or NUMBER.fullmatch(w)}


def _tokens(text: str) -> list[tuple[str, str]]:
    """The reader's tokens of a phrase as (kind, text): "num", "word", "sym", or "other" for a
    character the reader cannot read."""
    return [(match.lastgroup or "other", match.group().lower()) for match in TOKEN.finditer(text)]


def _readable(text: str) -> bool:
    """Every token is a word the reader knows, a number or a symbol it reads."""
    return all(
        kind in ("num", "sym") or (kind == "word" and word in KNOWN_WORDS)
        for kind, word in _tokens(text)
    )


def _brings_new(text: str) -> bool:
    """At least one word the reader does not know, or a character it cannot read. A number or a
    symbol is a word the reader knows (review and QA, 2026-10-28: "200 sma" or ">" brought
    nothing new, yet were learned and then changed sentences the reader had read)."""
    return any(
        kind == "other" or (kind == "word" and word not in KNOWN_WORDS)
        for kind, word in _tokens(text)
    )


def _context_free(text: str, frm: str, to: str) -> bool:
    if not frm or not to:
        return False
    pattern = r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, frm.split())) + r"(?![a-z0-9])"
    if not re.search(pattern, text.lower()):
        return False  # rule 1: not in the text
    if not _readable(to):
        return False  # rule 1: the reader would not read it
    if not _brings_new(frm):
        return False  # rule 2: nothing new
    return _operands(to) <= _operands(frm)  # rule 3


def _sides(text: str, strategy: StrategySpec, learned=None) -> dict | None:
    try:
        reading = read(text, strategy, learned=learned)
    except Unread:
        return None
    return {key: side.model_dump(mode="json") for key, side in reading.sides.items()}


class LearnedPhrases:
    def __init__(self, root: Path):
        self.folder = Path(root) / "phrases"
        self.path = self.folder / "learned.json"
        self.examples_path = self.folder / "examples.jsonl"

    def list(self) -> list[dict]:
        try:
            entries = json.loads(_retry(lambda: self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []
        return entries if isinstance(entries, list) else []

    def pairs(self) -> list[tuple[str, str]]:
        return [(e["from"], e["to"]) for e in self.list()]

    def examples(self, limit: int = EXAMPLES_IN_PROMPT) -> list[dict]:
        with _LOCK:  # never read a line while learn() is still appending it
            try:
                lines = _retry(lambda: self.examples_path.read_text(encoding="utf-8")).splitlines()
            except OSError:
                return []
        kept = []
        for line in lines:
            try:
                kept.append(json.loads(line))
            except ValueError:
                continue  # a torn line (a crash mid-append) is skipped, as learned.json would be
        return kept[-limit:]

    def learn(
        self,
        text: str,
        rewrite: str,
        substitutions: list[dict],
        provenance: dict,
        strategy: StrategySpec,
    ) -> list[dict]:
        """Keep the example; keep and return the substitutions that pass the four rules."""
        listed = [
            (
                " ".join(str(s.get("from", "")).lower().split()),
                " ".join(str(s.get("to", "")).split()),
            )
            for s in substitutions
        ]
        listed = [(frm, to) for frm, to in listed if frm and to and frm != to.lower()]
        first: dict[str, str] = {}
        for frm, to in listed:
            first.setdefault(frm, to)  # the same from twice: the first meaning, which rule 4 checks
        listed = list(first.items())
        target = _sides(rewrite, strategy)
        explained = target is not None and _sides(text, strategy, learned=listed) == target
        now = datetime.now(UTC).isoformat()
        kept = []
        if explained:
            kept = [
                {
                    "id": uuid.uuid4().hex[:12],
                    "from": frm,
                    "to": to,
                    "learned_at": now,
                    "example": text,
                    "provider": provenance.get("provider"),
                }
                for frm, to in dict(listed).items()
                if _context_free(text, frm, to)
            ]
        with _LOCK:
            self.folder.mkdir(parents=True, exist_ok=True)
            if kept:
                fresh = {e["from"] for e in kept}
                self._write([e for e in self.list() if e["from"] not in fresh] + kept)
            example = {
                "text": text,
                "rewrite": rewrite,
                "substitutions": [{"from": f, "to": t} for f, t in listed],
                "provider": provenance.get("provider"),
                "model": provenance.get("model"),
                "run_id": provenance.get("run_id"),
                "accepted_at": now,
                "learned": [e["id"] for e in kept],
            }
            with self.examples_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(example, sort_keys=True) + "\n")
        return kept

    def remove(self, identifier: str) -> None:
        with _LOCK:
            entries = self.list()
            remaining = [e for e in entries if e["id"] != identifier]
            if len(remaining) == len(entries):
                raise KeyError(identifier)
            self._write(remaining)

    def _write(self, entries: list[dict]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(entries, indent=1, sort_keys=True), encoding="utf-8")
        _retry(lambda: tmp.replace(self.path))


__all__ = ["EXAMPLES_IN_PROMPT", "LearnedPhrases", "apply_learned"]
