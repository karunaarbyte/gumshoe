"""Pure aggregation over call records: no database, no HTTP."""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel

from gumshoe.decider import (
    Answer,
    CallRecord,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    answer_confidence,
    answer_verdict,
    answers_agree,
)
from gumshoe.stats.timeutil import to_utc_iso

# The game acts on confirms_pending in bands (yes at or above the gate, no at or below 1 minus
# it), not at 0.5, so two backends agree on it when they land in the same band. This is the
# agent's default gate; the API passes Settings.confirm_gate.
CONFIRM_GATE = 0.8
BANDED = frozenset({"confirms_pending"})
# The game acts on `weight` only as a band too: from this score on, the dramatic persona model
# speaks. Two scores that sit on the same side agree, however far apart they are (the agent's
# default; the API passes Settings.dramatic_from).
DRAMATIC_FROM = 2.5
WEIGHT = "weight"
ERROR = "(error)"  # the confusion matrix's column for decisions the shadow failed to answer
_EPSILON = 1e-9


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens. Zero for a backend nobody bills (local Nimble)."""

    usd_per_mtok_in: float = 0.0
    usd_per_mtok_out: float = 0.0


def estimated_cost(
    price: Price, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """None when the backend reported no tokens at all."""
    if input_tokens is None and output_tokens is None:
        return None
    usd = (input_tokens or 0) * price.usd_per_mtok_in + (
        output_tokens or 0
    ) * price.usd_per_mtok_out
    return round(usd / 1_000_000, 6)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, q in [0, 1]. None for no samples."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(q * len(ordered)), 1)
    return ordered[rank - 1]


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


class LatencyStats(BaseModel):
    p50: float | None
    p95: float | None
    mean: float | None


class BackendStats(BaseModel):
    """`latency_ms` measures the calls that answered; `error_latency_ms` the ones that failed,
    reported beside it because timeouts are the slowest tail and would otherwise vanish (a
    backend that often times out would look fast). Both follow the `include_cold` rule."""

    backend: str
    calls: int
    errors: int
    cold_calls: int
    used_calls: int
    latency_ms: LatencyStats
    error_latency_ms: LatencyStats
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    total_input_tokens: int
    total_output_tokens: int
    est_cost_usd: float  # from the configured prices; 0 when none are set
    mean_confidence: float | None
    role: str  # the role this backend mostly played on the node: primary or shadow


class NodeStats(BaseModel):
    """Per question first: the pooled `agreement_rate` is dominated by the questions asked most
    often, so a comparison view should lead with `question_agreement`."""

    node: str
    decisions: int
    fallbacks: int
    compared: int  # decisions where both backends answered and no fallback happened
    shadow_errors: int  # decisions (no fallback) whose shadow call failed: left out of `compared`
    question_agreement: dict[str, float]
    # primary's intent -> shadow's intent -> compared decisions (nodes asking "intent" only); the
    # shadow's "(error)" column counts the decisions it failed to answer
    intent_confusion: dict[str, dict[str, int]]
    # mean of (shadow score - primary score) per score question over the compared decisions: a
    # constant offset between the backends shows here, not as disagreement
    score_offset: dict[str, float]
    agreement_rate: float | None  # agreeing (decision, question) pairs / all such pairs
    backends: list[BackendStats]


class StatsReport(BaseModel):
    """Per-node comparison. `include_cold` changes the latency samples only: cold calls still
    count in `calls`, tokens, confidence and agreement, because their answers are valid."""

    generated_at: str
    since: str | None
    include_cold: bool
    nodes: list[NodeStats]


class AnswerView(BaseModel):
    verdict: str
    confidence: float


class CallView(BaseModel):
    backend: str
    role: str
    used: bool
    cold: bool
    latency_ms: float
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    est_cost_usd: float | None
    answers: dict[str, AnswerView]


class DecisionView(BaseModel):
    decision_id: str
    node: str
    ts: str
    fallback: bool
    state_preview: str
    calls: list[CallView]
    # per question both backends answered: do they agree by the server's own rule? Empty when the
    # decision is not a fair head-to-head (a fallback, or the shadow did not answer)
    agrees: dict[str, bool]


def _band(p: float, gate: float) -> str:
    if p >= gate - _EPSILON:
        return "yes"
    if p <= 1 - gate + _EPSILON:
        return "no"
    return "unsure"


def pair_agrees(
    question: str,
    primary: Answer,
    shadow: Answer,
    confirm_gate: float = CONFIRM_GATE,
    dramatic_from: float = DRAMATIC_FROM,
) -> bool:
    if question in BANDED and isinstance(primary, NoulAnswer) and isinstance(shadow, NoulAnswer):
        return _band(primary.noul, confirm_gate) == _band(shadow.noul, confirm_gate)
    if question == WEIGHT and isinstance(primary, ScoreAnswer) and isinstance(shadow, ScoreAnswer):
        return (primary.score >= dramatic_from - _EPSILON) == (
            shadow.score >= dramatic_from - _EPSILON
        )
    return answers_agree([primary, shadow])


def head_to_head(group: Sequence[CallRecord]) -> tuple[dict[str, Answer], dict[str, Answer]] | None:
    """The primary's and the shadow's answers to the questions both gave, when the decision is a
    fair comparison: no fallback, both answered, at least one shared question."""
    if any(c.fallback for c in group):
        return None
    primary = next((c for c in group if c.role == "primary" and c.answers is not None), None)
    shadow = next((c for c in group if c.role == "shadow" and c.answers is not None), None)
    if primary is None or shadow is None or primary.answers is None or shadow.answers is None:
        return None
    shared = primary.answers.keys() & shadow.answers.keys()
    if not shared:  # nothing to compare, so this is not a head-to-head
        return None
    return (
        {q: primary.answers[q] for q in shared},
        {q: shadow.answers[q] for q in shared},
    )


def _by_decision(calls: Iterable[CallRecord]) -> dict[str, list[CallRecord]]:
    groups: dict[str, list[CallRecord]] = defaultdict(list)
    for call in calls:
        groups[call.decision_id].append(call)
    return groups


def disagreeing(
    calls: Iterable[CallRecord],
    confirm_gate: float = CONFIRM_GATE,
    dramatic_from: float = DRAMATIC_FROM,
    question: str | None = None,
) -> list[CallRecord]:
    """The calls of the decisions where both backends answered and differ on some question (or,
    with `question`, on that one)."""
    kept: list[CallRecord] = []
    for group in _by_decision(calls).values():
        pair = head_to_head(group)
        if pair is None:
            continue
        asked = [question] if question is not None else list(pair[0])
        if any(
            q in pair[0] and not pair_agrees(q, pair[0][q], pair[1][q], confirm_gate, dramatic_from)
            for q in asked
        ):
            kept.extend(group)
    return kept


def build_report(
    calls: Iterable[CallRecord],
    *,
    include_cold: bool = False,
    since: datetime | None = None,
    prices: Mapping[str, Price] | None = None,
    confirm_gate: float = CONFIRM_GATE,
    dramatic_from: float = DRAMATIC_FROM,
) -> StatsReport:
    by_node: dict[str, list[CallRecord]] = defaultdict(list)
    for call in calls:
        by_node[call.node].append(call)
    return StatsReport(
        generated_at=datetime.now(UTC).isoformat(),
        since=to_utc_iso(since) if since else None,
        include_cold=include_cold,
        nodes=[
            _node_stats(node, rows, include_cold, prices or {}, confirm_gate, dramatic_from)
            for node, rows in sorted(by_node.items())
        ],
    )


def _node_stats(
    node: str,
    rows: list[CallRecord],
    include_cold: bool,
    prices: Mapping[str, Price],
    confirm_gate: float,
    dramatic_from: float,
) -> NodeStats:
    decisions = _by_decision(rows)
    compared = 0
    shadow_errors = 0
    agreeing: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    offsets: dict[str, list[float]] = defaultdict(list)
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for group in decisions.values():
        pair = head_to_head(group)
        if pair is None:
            if _shadow_failed(group):
                shadow_errors += 1
                missed = _primary_intent(group)
                if missed is not None:
                    confusion[missed][ERROR] += 1
            continue
        primary, shadow = pair
        compared += 1
        for question in primary:
            totals[question] += 1
            agreeing[question] += pair_agrees(
                question, primary[question], shadow[question], confirm_gate, dramatic_from
            )
            a, b = primary[question], shadow[question]
            if isinstance(a, ScoreAnswer) and isinstance(b, ScoreAnswer):
                offsets[question].append(b.score - a.score)
        said, heard = primary.get("intent"), shadow.get("intent")
        if isinstance(said, ChoiceAnswer) and isinstance(heard, ChoiceAnswer):
            confusion[said.choice][heard.choice] += 1

    all_pairs = sum(totals.values())
    return NodeStats(
        node=node,
        decisions=len(decisions),
        fallbacks=sum(any(c.fallback for c in group) for group in decisions.values()),
        compared=compared,
        shadow_errors=shadow_errors,
        question_agreement={q: agreeing[q] / totals[q] for q in sorted(totals)},
        intent_confusion={a: dict(sorted(b.items())) for a, b in sorted(confusion.items())},
        score_offset={q: round(sum(v) / len(v), 4) for q, v in sorted(offsets.items())},
        agreement_rate=sum(agreeing.values()) / all_pairs if all_pairs else None,
        backends=[
            _backend_stats(
                name, [r for r in rows if r.backend == name], include_cold, prices.get(name)
            )
            for name in sorted({r.backend for r in rows})
        ],
    )


def _shadow_failed(group: Sequence[CallRecord]) -> bool:
    """A decision with no fallback whose shadow call failed (so it never reached `compared`)."""
    if any(c.fallback for c in group):
        return False
    return any(c.role == "shadow" and c.error is not None for c in group)


def _primary_intent(group: Sequence[CallRecord]) -> str | None:
    primary = next((c for c in group if c.role == "primary" and c.answers is not None), None)
    said = primary.answers.get("intent") if primary is not None and primary.answers else None
    return said.choice if isinstance(said, ChoiceAnswer) else None


def _latency(rows: list[CallRecord], include_cold: bool) -> LatencyStats:
    values = [r.latency_ms for r in rows if include_cold or not r.cold]
    return LatencyStats(
        p50=percentile(values, 0.5), p95=percentile(values, 0.95), mean=_mean(values)
    )


def _backend_stats(
    backend: str, rows: list[CallRecord], include_cold: bool, price: Price | None
) -> BackendStats:
    ok = [r for r in rows if r.error is None]
    failed = [r for r in rows if r.error is not None]
    total_in = sum(r.input_tokens or 0 for r in rows)  # a failed call may still be billed
    total_out = sum(r.output_tokens or 0 for r in rows)
    return BackendStats(
        backend=backend,
        calls=len(rows),
        errors=len(failed),
        cold_calls=sum(r.cold for r in rows),
        used_calls=sum(r.used for r in rows),
        latency_ms=_latency(ok, include_cold),
        error_latency_ms=_latency(failed, include_cold),
        mean_input_tokens=_mean([r.input_tokens for r in ok if r.input_tokens is not None]),
        mean_output_tokens=_mean([r.output_tokens for r in ok if r.output_tokens is not None]),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        est_cost_usd=estimated_cost(price or Price(), total_in, total_out) or 0.0,
        mean_confidence=_mean([r.mean_confidence for r in ok if r.mean_confidence is not None]),
        role="shadow" if sum(r.role == "shadow" for r in rows) * 2 > len(rows) else "primary",
    )


def recent_decisions(
    calls: Iterable[CallRecord],
    *,
    prices: Mapping[str, Price] | None = None,
    confirm_gate: float = CONFIRM_GATE,
    dramatic_from: float = DRAMATIC_FROM,
) -> list[DecisionView]:
    """Group calls by decision, newest decision first."""
    groups = _by_decision(calls)
    priced = prices or {}
    views = [
        DecisionView(
            decision_id=decision_id,
            node=group[0].node,
            ts=min(c.ts for c in group),
            fallback=any(c.fallback for c in group),
            state_preview=group[0].state_preview,
            calls=[
                _call_view(c, priced.get(c.backend))
                for c in sorted(group, key=lambda c: c.role != "primary")
            ],
            agrees=_agrees(group, confirm_gate, dramatic_from),
        )
        for decision_id, group in groups.items()
    ]
    return sorted(views, key=lambda v: v.ts, reverse=True)


def _agrees(
    group: Sequence[CallRecord], confirm_gate: float, dramatic_from: float
) -> dict[str, bool]:
    pair = head_to_head(group)
    if pair is None:
        return {}
    primary, shadow = pair
    return {
        q: pair_agrees(q, primary[q], shadow[q], confirm_gate, dramatic_from)
        for q in sorted(primary)
    }


def _call_view(call: CallRecord, price: Price | None) -> CallView:
    answers = call.answers or {}
    return CallView(
        backend=call.backend,
        role=call.role,
        used=call.used,
        cold=call.cold,
        latency_ms=call.latency_ms,
        error=call.error,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        est_cost_usd=estimated_cost(price or Price(), call.input_tokens, call.output_tokens),
        answers={
            q: AnswerView(verdict=answer_verdict(a), confidence=round(answer_confidence(a), 3))
            for q, a in answers.items()
        },
    )
