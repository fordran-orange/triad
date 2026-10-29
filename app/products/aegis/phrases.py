"""The phrase reader (Mission 13 spec §4.7 and §9): a deterministic reading of a trading sentence
into whole replacement sides, such as "buy when 9 ema crosses 30 sma and price is above 200 sma".

Nothing is guessed. A word it cannot place refuses the whole text, naming the words and where
they are. The later AI step through Core answers the same request with the same `Reading`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from products.aegis.kinds import KINDS
from products.aegis.strategy import StrategySide, StrategySpec

DEFAULT_STOP, DEFAULT_TARGET = 2.0, 5.0
SideKey = Literal["long_side", "short_side"]
SIDE_KEYS: dict[str, SideKey] = {"long": "long_side", "short": "short_side"}

OPENERS: list[tuple[tuple[str, ...], str, str]] = [  # longest first
    (("sell", "short", "when"), "short", "entry"),
    (("go", "long", "when"), "long", "entry"),
    (("go", "short", "when"), "short", "entry"),
    (("buy", "when"), "long", "entry"),
    (("long", "when"), "long", "entry"),
    (("short", "when"), "short", "entry"),
    (("sell", "when"), "long", "exit"),
    (("exit", "when"), "long", "exit"),
    (("close", "when"), "long", "exit"),
    (("cover", "when"), "short", "exit"),
]
KIND_WORDS = {
    "ema": "EMA",
    "sma": "SMA",
    "rsi": "RSI",
    "atr": "ATR",
    "bb": "BB",
    "bollinger": "BB",
    "donchian": "DONCHIAN",
    "macd": "MACD",
}
OUTPUT_WORDS = {"upper", "middle", "lower", "line", "signal", "histogram"}
PRICE_WORDS = {"price": "close", "close": "close", "open": "open", "high": "high", "low": "low"}
LEVEL_WORDS = {"stop", "target", "take", "profit"}
COMPARISON_WORDS = {
    "crosses",
    "cross",
    "above",
    "over",
    "below",
    "under",
    "is",
    "greater",
    "less",
    "than",
    "inside",
    "outside",
}
# Every word the reader reads (Mission 14): a learned phrase must bring at least one word outside
# this set, so it can never change a sentence the reader already understood.
KNOWN_WORDS = frozenset(
    {word for words, _side, _role in OPENERS for word in words}
    | set(KIND_WORDS)
    | OUTPUT_WORDS
    | set(PRICE_WORDS)
    | LEVEL_WORDS
    | COMPARISON_WORDS
    | {"and", "or", "loss", "at", "with", "a", "the", "band", "bands", "when"}
)
LABELS = {
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
    "greater_than": "above",
    "less_than": "below",
    "inside_band": "inside",
    "outside_band": "outside",
}
TOKEN = re.compile(
    r"(?P<num>\d+(?:\.\d+)?%?)|(?P<word>[a-z]+)|(?P<sym>[()<>,;.])|(?P<other>\S)", re.IGNORECASE
)


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2_000)
    strategy: StrategySpec
    # Mission 14: who reads what this cannot; ai=False when the builder offers no provider, so only
    # the phrase reader reads
    provider: Literal["CLAUDE", "CODEX", "GROK"] | None = None
    ai: bool = True


class Reading(BaseModel):
    """Whole replacement sides, a one-line reading back, and the paths that are defaults. Mission
    14: who read it, and for an AI reading the rewrite the reader read, the substitutions, what
    could not be expressed and Core's provenance."""

    model_config = ConfigDict(extra="forbid")
    sides: dict[SideKey, StrategySide]
    reading: str
    defaults: list[str]
    read_by: Literal["phrases", "ai"] = "phrases"
    rewrite: str | None = None
    substitutions: list[dict] = Field(default_factory=list)
    unsupported: str = ""
    provenance: dict | None = None


class Unread(ValueError):
    """Text the reader could not read: the message and the spans (character offsets) it names."""

    def __init__(self, message: str, spans: list[dict]) -> None:
        super().__init__(message)
        self.spans = spans


@dataclass(frozen=True)
class Token:
    kind: str  # num | word | sym
    text: str  # lowercased
    start: int
    end: int


@dataclass(frozen=True)
class Indicator:
    kind: str
    length: int
    params: tuple[tuple[str, float], ...]  # only values that differ from the kind's defaults


@dataclass(frozen=True)
class Operand:
    price: str | None = None
    constant: str | None = None
    indicator: Indicator | None = None
    output: str | None = None


@dataclass
class Condition:
    left: Operand
    operator: str
    right: Operand


@dataclass
class Group:
    join: str  # all_of | any_of
    members: list


@dataclass
class Plan:
    """What the text says about one side."""

    entry: Condition | Group | None = None
    exit: Condition | Group | None = None
    stop: float | None = None
    target: float | None = None
    mentions: list[Indicator] = field(default_factory=list)


def _span(tokens: list[Token], text: str) -> dict:
    start, end = tokens[0].start, tokens[-1].end
    return {"start": start, "end": end, "text": text[start:end]}


def tokenize(text: str) -> list[Token]:
    tokens = []
    for match in TOKEN.finditer(text):
        kind = match.lastgroup
        if kind == "other":
            word = match.group()
            raise Unread(
                f"didn't understand '{word}'",
                [{"start": match.start(), "end": match.end(), "text": word}],
            )
        tokens.append(Token(kind, match.group().lower(), match.start(), match.end()))
    return tokens


def _clauses(tokens: list[Token]) -> list[list[Token]]:
    """Split on ';' and '.' outside brackets, and on ',' or 'and' that starts a new clause (an
    opener follows: "buy when …, sell when …", Mission 14)."""
    clauses, current, depth = [], [], 0
    for i, token in enumerate(tokens):
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        joint = token.text in (",", "and") and _opener(tokens[i + 1 :]) is not None
        if depth == 0 and (token.text in (";", ".") or joint):
            if current:
                clauses.append(current)
            current = []
            continue
        current.append(token)
    if current:
        clauses.append(current)
    return clauses


class Reader:
    """Recursive descent over one clause's tokens."""

    def __init__(self, tokens: list[Token], text: str, side: str, role: str) -> None:
        self.tokens, self.text, self.side, self.role = tokens, text, side, role
        self.i = 0

    # -- the stream ---------------------------------------------------------------------------
    def peek(self, offset: int = 0) -> Token | None:
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else None

    def word(self, offset: int = 0) -> str | None:
        token = self.peek(offset)
        return token.text if token is not None else None

    def take(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def unread(self, message: str, tokens: list[Token]) -> Unread:
        return Unread(message, [_span(tokens, self.text)])

    def unknown(self, token: Token) -> Unread:
        return self.unread(f"didn't understand '{self.text[token.start : token.end]}'", [token])

    # -- expressions --------------------------------------------------------------------------
    def expression(self) -> Condition | Group:
        terms = [self.term()]
        while self.word() == "or":
            self.take()
            terms.append(self.term())
        return terms[0] if len(terms) == 1 else Group("any_of", terms)

    def term(self) -> Condition | Group:
        factors = [self.factor()]
        while self.word() == "and" and not self.level_ahead(1):
            self.take()
            factors.append(self.factor())
        return factors[0] if len(factors) == 1 else Group("all_of", factors)

    def factor(self) -> Condition | Group:
        if self.word() == "(":
            opening = self.take()
            inner = self.expression()
            if self.word() != ")":
                raise self.unread("a bracket is not closed", [opening])
            self.take()
            return inner
        return self.condition()

    def condition(self) -> Condition:
        if self.peek() is None:
            raise self.unread("this clause has no condition", [self.tokens[-1]])
        left = self.operand()
        start = self.i
        if self.word() == "is":
            self.take()
        word = self.word()
        if word in ("crosses", "cross"):
            self.take()
            direction = self.word()
            if direction in ("above", "over"):
                self.take()
                operator = "crosses_above"
            elif direction in ("below", "under"):
                self.take()
                operator = "crosses_below"
            else:  # spec §9.4: a bare "crosses" follows the clause's direction
                up = (self.side, self.role) in (("long", "entry"), ("short", "exit"))
                operator = "crosses_above" if up else "crosses_below"
        elif word in ("above", ">"):
            self.take()
            operator = "greater_than"
        elif word in ("below", "<"):
            self.take()
            operator = "less_than"
        elif word in ("greater", "less") and self.word(1) == "than":
            self.take()
            self.take()
            operator = "greater_than" if word == "greater" else "less_than"
        elif word in ("inside", "outside"):
            self.take()
            operator = "inside_band" if word == "inside" else "outside_band"
        else:
            token = self.peek()
            if token is None:
                raise self.unread("a condition needs a comparison", self.tokens[start - 1 : start])
            raise self.unknown(token)
        compare = self.tokens[start : self.i]
        if self.peek() is None or self.word() in (")", "and", "or", ",") or self.level_ahead(0):
            raise self.unread(f"{compare[-1].text} needs something on its right", compare)
        band = compare[-1].text if operator in ("inside_band", "outside_band") else None
        right = self.operand(band=band)
        return Condition(left, operator, right)

    def operand(self, band: str | None = None) -> Operand:
        """A number, a price, or an indicator; `band` names the comparison ("inside") when the
        operand must be a whole band."""
        if self.word() == "the":
            self.take()
        token = self.peek()
        if token is None:
            raise self.unread("something is missing here", [self.tokens[-1]])
        if token.kind == "num":
            if token.text.endswith("%"):
                raise self.unread("a percentage belongs to a stop or a target", [token])
            if self.word(1) in KIND_WORDS:
                self.take()
                return self.indicator(length=token, band=band)
            self.take()
            if band:
                raise self.unread(f"{band} needs a band (bb or donchian)", [token])
            return Operand(constant=token.text)
        if token.text in PRICE_WORDS:
            self.take()
            if band:
                raise self.unread(f"{band} needs a band (bb or donchian)", [token])
            return Operand(price=PRICE_WORDS[token.text])
        if token.text in OUTPUT_WORDS and self.word(1) in KIND_WORDS:
            self.take()
            return self.indicator(output=token, band=band)
        if token.text in KIND_WORDS:
            return self.indicator(band=band)
        raise self.unknown(token)

    def indicator(
        self, length: Token | None = None, output: Token | None = None, band: str | None = None
    ) -> Operand:
        """`9 ema`, `ema 9`, `ema(9)`, `bb 20 2`, `macd line`, `upper bb 20`."""
        first = self.i - (1 if length is not None or output is not None else 0)
        name = self.take()
        kind = KIND_WORDS[name.text]
        info = KINDS[kind]
        numbers: list[Token] = [length] if length is not None else []
        if self.word() == "(" and self.peek(1) is not None and self.peek(1).kind == "num":
            self.take()
            while self.peek() is not None and self.peek().kind == "num":
                numbers.append(self.take())
                if self.word() == ",":
                    self.take()
            if self.word() != ")":
                raise self.unread("a bracket is not closed", [name])
            self.take()
        else:
            while (
                self.peek() is not None
                and self.peek().kind == "num"
                and self.word(1) not in KIND_WORDS
            ):
                if self.peek().text.endswith("%"):
                    break
                numbers.append(self.take())
        allowed = 1 + len(info.params)
        if len(numbers) > allowed:
            raise self.unread(
                f"{name.text} takes at most {allowed} number{'s' if allowed > 1 else ''}",
                numbers[allowed:],
            )
        values = [float(n.text) for n in numbers]
        names = ["length", *info.params]
        whole = {"length", *info.integer_params}
        for number, value, key in zip(numbers, values, names, strict=False):
            if key in whole and not value.is_integer():
                raise self.unread(f"{name.text}'s {key} is a whole number", [number])
        length_value = int(values[0]) if values else info.default_length
        params = tuple(
            (key, value)
            for key, value in zip(names[1:], values[1:], strict=False)
            if value != info.params[key]
        )
        if output is None and self.word() in OUTPUT_WORDS:
            output = self.take()
        if self.word() in ("band", "bands"):
            self.take()
        if output is not None and output.text not in info.outputs:
            raise self.unread(f"{name.text} has no output '{output.text}'", [output])
        words = self.tokens[first : self.i]
        if band is not None:
            if not {"upper", "lower"} <= set(info.outputs):
                raise self.unread(f"{band} needs a band (bb or donchian)", words)
            if output is not None:
                raise self.unread(f"{band} takes the whole band: drop '{output.text}'", [output])
        elif info.outputs and output is None:
            raise self.unread(
                f"{name.text} has outputs {', '.join(info.outputs)}: name one, e.g. "
                f"'{name.text} {info.outputs[0]}'",
                words,
            )
        return Operand(
            indicator=Indicator(kind, length_value, params),
            output=output.text if output is not None else None,
        )

    # -- levels -------------------------------------------------------------------------------
    def level_ahead(self, offset: int) -> bool:
        word, after = self.word(offset), self.word(offset + 1)
        token = self.peek(offset)
        if word in ("stop", "target", "take"):
            return True
        if word == "profit" and after == "target":
            return True
        return bool(
            token is not None and token.kind == "num" and after in ("stop", "target", "take")
        )

    def level(self) -> tuple[str, float, list[Token]]:
        """A stop or a target: `stop at 2%`, `2% stop`, `take profit at 5%`, `target 5%`."""
        start = self.i
        number: Token | None = None
        if self.peek() is not None and self.peek().kind == "num":
            number = self.take()
        if self.word() == "stop":
            self.take()
            if self.word() == "loss":
                self.take()
            which = "stop"
        elif self.word() == "target":
            self.take()
            which = "target"
        elif (
            self.word() == "take"
            and self.word(1) == "profit"
            or self.word() == "profit"
            and self.word(1) == "target"
        ):
            self.take()
            self.take()
            which = "target"
        else:
            token = self.peek() or self.tokens[-1]
            raise self.unknown(token)
        if number is None:
            if self.word() == "at":
                self.take()
            if self.peek() is not None and self.peek().kind == "num":
                number = self.take()
        phrase = self.tokens[start : self.i]
        name = "stop" if which == "stop" else "take profit"
        example = "2%" if which == "stop" else "5%"
        if number is None or not number.text.endswith("%"):
            raise self.unread(f"write a {name} as a percentage, e.g. {example}", phrase)
        return which, float(number.text[:-1]), phrase

    def levels(self, plan: Plan) -> None:
        """Levels after a clause's condition, or a clause of levels alone."""
        while self.peek() is not None:
            if self.word() in (",", "with", "and", "a"):
                self.take()
                continue
            if not self.level_ahead(0):
                raise self.unknown(self.peek())
            which, value, phrase = self.level()
            if getattr(plan, which) is not None:
                kind = "stop losses" if which == "stop" else "take profits"
                raise self.unread(f"two {kind}", phrase)
            setattr(plan, which, value)


def _opener(tokens: list[Token]) -> tuple[str, str, int] | None:
    words = tuple(t.text for t in tokens)
    for pattern, side, role in OPENERS:
        if words[: len(pattern)] == pattern:
            return side, role, len(pattern)
    return None


def _plans(text: str) -> tuple[dict[str, Plan], list[str]]:
    """Each side's plan, and the sides in the order the text names them."""
    plans: dict[str, Plan] = {}
    order: list[str] = []
    side = "long"
    tokens = tokenize(text)
    if not tokens:
        raise Unread("there is nothing to read", [])
    for clause in _clauses(tokens):
        opened = _opener(clause)
        if opened is None:
            reader = Reader(clause, text, side, "levels")
            if not reader.level_ahead(0):
                raise reader.unknown(clause[0])
            plan = plans.setdefault(side, Plan())
            if side not in order:
                order.append(side)
            reader.levels(plan)
            continue
        side, role, used = opened
        reader = Reader(clause[used:], text, side, role)
        if not reader.tokens:
            raise Unread("this clause has no condition", [_span(clause, text)])
        plan = plans.setdefault(side, Plan())
        if side not in order:
            order.append(side)
        if getattr(plan, role) is not None:
            raise Unread(f"two {side} {role}s", [_span(clause, text)])
        setattr(plan, role, reader.expression())
        reader.levels(plan)
    return plans, order


def _mentions(node) -> list[Indicator]:
    if isinstance(node, Condition):
        return [o.indicator for o in (node.left, node.right) if o.indicator is not None]
    return [i for member in node.members for i in _mentions(member)]


def _spec_of(indicator: Indicator, identifier: str) -> dict:
    spec: dict = {"id": identifier, "kind": indicator.kind, "length": indicator.length}
    if indicator.params:
        spec["params"] = dict(indicator.params)
    return spec


def _matches(existing: dict, indicator: Indicator) -> bool:
    return (
        str(existing.get("kind", "")).upper() == indicator.kind
        and existing.get("length") == indicator.length
        and existing.get("source", "close") == "close"
        and dict(existing.get("params") or {}) == dict(indicator.params)
    )


def _ids(mentions: list[Indicator], kept: list[dict]) -> dict[Indicator, str]:
    """Spec §9.2: an indicator alone of its kind takes the kind's name; two of a kind take kind and
    length; a further clash takes `_2`. A kept indicator with the same settings is reused."""
    ids: dict[Indicator, str] = {}
    fresh: list[Indicator] = []
    for indicator in dict.fromkeys(mentions):
        reused = next((k["id"] for k in kept if _matches(k, indicator)), None)
        if reused is not None:
            ids[indicator] = reused
        else:
            fresh.append(indicator)
    taken = {k["id"] for k in kept}
    for indicator in fresh:
        kind = indicator.kind.lower()
        same = [i for i in fresh if i.kind == indicator.kind]
        same_kept = [k for k in kept if str(k.get("kind", "")).upper() == indicator.kind]
        base = kind if len(same) + len(same_kept) == 1 else f"{kind}{indicator.length}"
        identifier, n = base, 2
        while identifier in taken:
            identifier, n = f"{base}_{n}", n + 1
        taken.add(identifier)
        ids[indicator] = identifier
    return ids


def _operand(operand: Operand, ids: dict[Indicator, str]) -> str:
    if operand.price is not None:
        return f"price.{operand.price}"
    if operand.constant is not None:
        return operand.constant
    identifier = ids[operand.indicator]
    return f"{identifier}.{operand.output}" if operand.output else identifier


def _rule(node, ids: dict[Indicator, str]) -> dict:
    if isinstance(node, Condition):
        return {
            "left": _operand(node.left, ids),
            "operator": node.operator,
            "right": _operand(node.right, ids),
        }
    return {node.join: [_rule(member, ids) for member in node.members]}


def _label(operand: Operand) -> str:
    if operand.price is not None:
        return operand.price
    if operand.constant is not None:
        return operand.constant
    indicator = operand.indicator
    name = " ".join(
        [indicator.kind, str(indicator.length), *(f"{v:g}" for _, v in indicator.params)]
    )
    return f"{name} {operand.output}" if operand.output else name


def _words(node, parent: str | None = None) -> str:
    if isinstance(node, Condition):
        return f"{_label(node.left)} {LABELS[node.operator]} {_label(node.right)}"
    joined = (" OR " if node.join == "any_of" else " AND ").join(
        _words(member, node.join) for member in node.members
    )
    return f"({joined})" if parent is not None and parent != node.join else joined


ROLE_NAMES = {
    ("long", "entry"): "a long entry",
    ("long", "exit"): "a long exit",
    ("short", "entry"): "a short entry",
    ("short", "exit"): "a short exit",
}


def grammar_text() -> str:
    """The reader's language, generated from its own tables (Mission 14): what the AI is asked to
    write, so the two can never drift apart."""
    openers = "; ".join(
        f"{name}: " + ", ".join(f'"{" ".join(w)}"' for w, s, r in OPENERS if (s, r) == key)
        for key, name in ROLE_NAMES.items()
    )
    names = {}
    for word, kind in KIND_WORDS.items():
        names.setdefault(kind, []).append(word)
    kinds = "; ".join(
        " or ".join(f'"{w}"' for w in words)
        + f" ({', '.join(['length', *KINDS[kind].params])}"
        + (f"; outputs {', '.join(KINDS[kind].outputs)}" if KINDS[kind].outputs else "")
        + ")"
        for kind, words in names.items()
    )
    return (
        "The reader's language. Clauses are separated by ';' (a ',' or 'and' may also come before "
        f"a new opener). Openers: {openers}. Conditions: '<a> crosses above <b>', '<a> crosses "
        "below <b>', '<a> is above <b>', '<a> is below <b>', '<a> inside <band>', '<a> outside "
        "<band>'; join conditions with 'and' / 'or' and brackets ('and' binds before 'or'). "
        "Operands: 'close', 'open', 'high', 'low' ('price' means close); a plain number; an "
        "indicator written '<length> <kind>' or '<kind> <length> [settings]', its output after it "
        f"('donchian 20 upper', 'macd line'). Kinds: {kinds}. A band for inside / outside is "
        "'bb <length>' or 'donchian <length>' with no output. Exits by level: 'stop at <N>%' and "
        "'take profit at <N>%', after a clause or as a clause of their own. Repeat operands; "
        "never use pronouns."
    )


def apply_learned(text: str, learned: list[tuple[str, str]]) -> tuple[str, list[int], list[int]]:
    """The text with learned phrases replaced (whole words, any case, the leftmost match first and
    among phrases starting there the longest, never overlapping), and for every character of the
    result the start and end of the original characters it came from."""
    pairs = sorted(
        ((" ".join(frm.lower().split()), to) for frm, to in learned if frm.split()),
        key=lambda pair: -len(pair[0]),
    )
    if not pairs:
        return text, list(range(len(text))), list(range(1, len(text) + 1))
    pattern = re.compile(
        "|".join(
            f"(?P<p{i}>(?<![a-z0-9]){r'\s+'.join(map(re.escape, frm.split()))}(?![a-z0-9]))"
            for i, (frm, _to) in enumerate(pairs)
        ),
        re.IGNORECASE,
    )
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    at = 0
    for match in pattern.finditer(text):
        for j in range(at, match.start()):
            out.append(text[j])
            starts.append(j)
            ends.append(j + 1)
        for character in pairs[int(match.lastgroup[1:])][1]:
            out.append(character)
            starts.append(match.start())
            ends.append(match.end())
        at = match.end()
    for j in range(at, len(text)):
        out.append(text[j])
        starts.append(j)
        ends.append(j + 1)
    return "".join(out), starts, ends


def read(
    text: str, strategy: StrategySpec, learned: list[tuple[str, str]] | None = None
) -> Reading:
    """The sides `text` describes, built on `strategy` (an exit clause alone keeps its side's
    entry and indicators). Learned phrases (Mission 14) are applied first; a refusal still names
    the operator's own words."""
    if not learned:
        return _read(text, strategy)
    rewritten, starts, ends = apply_learned(text, learned)
    try:
        return _read(rewritten, strategy)
    except Unread as exc:
        spans = []
        for span in exc.spans:
            start, end = starts[span["start"]], ends[span["end"] - 1]
            spans.append({"start": start, "end": end, "text": text[start:end]})
        raise Unread(str(exc), spans) from None


def _read(text: str, strategy: StrategySpec) -> Reading:
    plans, order = _plans(text)
    sides: dict[SideKey, StrategySide] = {}
    lines: list[str] = []
    defaults: list[str] = []
    for side in order:
        plan, key = plans[side], SIDE_KEYS[side]
        current = getattr(strategy, key).model_dump(mode="json")
        if plan.entry is None and plan.exit is None:
            # levels alone change only the side's levels
            data = current
        elif plan.entry is None:
            data = current
        else:
            data = {"direction": side, "enabled": True, "indicators": [], "optimization": []}
        kept = data["indicators"] if plan.entry is None else []
        mentions = [
            i for node in (plan.entry, plan.exit) if node is not None for i in _mentions(node)
        ]
        ids = _ids(mentions, kept)
        indicators = list(kept)
        for indicator, identifier in ids.items():
            if identifier not in {k["id"] for k in indicators}:
                indicators.append(_spec_of(indicator, identifier))
        data["indicators"] = indicators
        if plan.entry is not None:
            data["entry"] = _rule(plan.entry, ids)
            data.pop("exit", None)
            data.pop("stop_loss_pct", None)
            data.pop("take_profit_pct", None)
        if plan.exit is not None:
            data["exit"] = _rule(plan.exit, ids)
        defaulted = (
            plan.entry is not None
            and plan.exit is None
            and plan.stop is None
            and plan.target is None
        )
        if defaulted:
            plan.stop, plan.target = DEFAULT_STOP, DEFAULT_TARGET
            defaults += [f"{key}.stop_loss_pct", f"{key}.take_profit_pct"]
        if plan.stop is not None:
            data["stop_loss_pct"] = plan.stop
        if plan.target is not None:
            data["take_profit_pct"] = plan.target
        try:
            sides[key] = StrategySide.model_validate(data)
        except ValidationError as exc:
            message = exc.errors()[0]["msg"].removeprefix("Value error, ")
            raise Unread(f"{side} side: {message}", []) from None
        lines.append(_reading(side, plan, defaulted))
    return Reading(sides=sides, reading=". ".join(lines), defaults=defaults)


def _reading(side: str, plan: Plan, defaulted: bool) -> str:
    exits = [_words(plan.exit)] if plan.exit is not None else []
    if plan.stop is not None:
        exits.append(f"stop loss {plan.stop:g}%")
    if plan.target is not None:
        exits.append(f"take profit {plan.target:g}%")
    exit_text = ", ".join(exits) + (" (default)" if defaulted else "")
    name = side.capitalize()
    if plan.entry is None and plan.exit is None:
        return f"{name} side: {exit_text}"
    if plan.entry is None:
        return f"{name} exit: {exit_text}"
    return f"{name} entry: {_words(plan.entry)}. Exit: {exit_text}"


__all__ = [
    "DEFAULT_STOP",
    "DEFAULT_TARGET",
    "KNOWN_WORDS",
    "ReadRequest",
    "Reading",
    "Unread",
    "apply_learned",
    "grammar_text",
    "read",
]
