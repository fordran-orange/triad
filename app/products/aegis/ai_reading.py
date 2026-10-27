"""Reading a sentence with a model through Core (Mission 14 spec §4.2).

The model rewrites the operator's sentence into the phrase reader's own language and lists the
substitutions it made; the phrase reader then reads the rewrite, so everything that reaches the
builder went through the same deterministic path.
"""

from __future__ import annotations

from products.aegis.core_client import CoreReadingError
from products.aegis.phrases import Reading, Unread, grammar_text, read
from products.aegis.strategy import StrategySpec

# The subscription CLIs; each is offered only while Core can route a reading to it (operator,
# 2026-10-27: "grok should be an option if available").
PROVIDERS = {"CLAUDE": "Claude", "CODEX": "Codex", "GROK": "Grok"}
OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["rewrite", "substitutions", "unsupported"],
    "properties": {
        "rewrite": {"type": "string"},
        "substitutions": {"type": "array"},
        "unsupported": {"type": "string"},
    },
}


class AIUnread(Exception):
    """Why the AI could not give a reading: a reason, a message, the provider, the rewrite."""

    def __init__(self, reason: str, message: str, provider: str, rewrite: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.provider = provider
        self.rewrite = rewrite

    def detail(self) -> dict:
        detail = {"reason": self.reason, "message": str(self), "provider": self.provider}
        if self.rewrite is not None:
            detail["rewrite"] = self.rewrite
        return detail


def instructions(strategy: StrategySpec, examples: list[dict]) -> str:
    """What the model is asked: the reader's grammar, the strategy's indicators, the rules and the
    newest accepted examples."""
    sides = []
    for key, name in (("long_side", "long"), ("short_side", "short")):
        indicators = getattr(strategy, key).indicators
        listed = ", ".join(f"{i.id} ({i.kind.upper()} {i.length})" for i in indicators)
        sides.append(f"{name} side: {listed or 'none'}")
    parts = [
        (
            "You rewrite a trader's sentence into the strategy reader's language so the reader "
            "can read it."
        ),
        grammar_text(),
        "The strategy's indicators now: " + "; ".join(sides) + ".",
        (
            "Rules: write only the reader's language. Never use pronouns: repeat the operand. "
            "Never add a condition, number or indicator the trader did not state. List every "
            "change you made as a substitution, 'from' being the trader's exact words and 'to' "
            "the words you wrote. Put anything you could not express in 'unsupported', or an "
            "empty string."
        ),
        (
            'Answer with JSON only: {"rewrite": "...", "substitutions": [{"from": "...", '
            '"to": "..."}], "unsupported": "..."}.'
        ),
    ]
    if examples:
        parts.append(
            "Accepted readings so far (sentence -> rewrite):\n"
            + "\n".join(f'"{e["text"]}" -> "{e["rewrite"]}"' for e in examples)
        )
    return "\n\n".join(parts)


def _explain(exc: CoreReadingError, name: str) -> tuple[str, str]:
    detail = str(exc)
    if exc.reason == "provider_failed":
        return "provider_failed", f"{name} could not read this: {detail}"
    if exc.reason in ("not_issued", "refused"):
        return "not_set_up", f"AI reading is not set up: {detail}"
    if exc.reason == "core_unavailable":
        return "core_unavailable", "Core is not answering; the AI cannot read this now"
    if exc.reason == "busy":
        return "busy", "a reading is still finishing; try again in a moment"
    if exc.reason == "timed_out":
        return "timed_out", f"{name} took too long (over 120 s); try again"
    if exc.reason == "malformed_answer":
        return "malformed_answer", f"{name}'s answer could not be used: {detail}"
    return exc.reason, f"{name} could not read this: {detail}"


def available_providers(client) -> dict:
    """Each provider with whether Core can route a reading to it now; when Core cannot say, none
    is available and the message says why."""
    try:
        routable = {p["provider"] for p in client.providers() if p.get("available") is True}
        message = None
    except CoreReadingError as exc:
        routable, message = set(), _explain(exc, "The AI")[1]
    return {
        "providers": [
            {"id": p, "name": name, "available": p in routable} for p, name in PROVIDERS.items()
        ],
        "message": message,
    }


def read_with_ai(
    text: str, strategy: StrategySpec, provider: str, client, examples: list[dict]
) -> Reading:
    """The reading the model's rewrite gives, or AIUnread with why not."""
    name = PROVIDERS.get(provider, provider.title())
    try:
        answer = client.reason(provider, instructions(strategy, examples), text, OUTPUT_SCHEMA)
    except CoreReadingError as exc:
        raise AIUnread(*_explain(exc, name), provider) from exc
    output = answer.get("output") or {}
    rewrite = str(output.get("rewrite", ""))
    try:
        reading = read(rewrite, strategy)
    except Unread as exc:
        raise AIUnread(
            "rewrite_unread", f"{name}'s rewrite could not be read: {exc}", provider, rewrite
        ) from exc
    substitutions = [
        {"from": s["from"], "to": s["to"]}
        for s in output.get("substitutions") or []
        if isinstance(s, dict) and isinstance(s.get("from"), str) and isinstance(s.get("to"), str)
    ]
    return reading.model_copy(
        update={
            "read_by": "ai",
            "rewrite": rewrite,
            "substitutions": substitutions,
            "unsupported": str(output.get("unsupported", "")),
            "provenance": answer.get("provenance"),
        }
    )


__all__ = [
    "OUTPUT_SCHEMA",
    "PROVIDERS",
    "AIUnread",
    "available_providers",
    "instructions",
    "read_with_ai",
]
