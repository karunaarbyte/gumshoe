"""Pure aggregation over call records: no database, no HTTP."""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from gumshoe.decider import CallRecord, answer_confidence, answer_verdict, answers_agree
from gumshoe.stats.timeutil import to_utc_iso


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
    backend: str
    calls: int
    errors: int
    cold_calls: int
    used_calls: int
    latency_ms: LatencyStats
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    mean_confidence: float | None


class NodeStats(BaseModel):
    node: str
    decisions: int
    fallbacks: int
    compared: int  # decisions where both backends answered and no fallback happened
    agreement_rate: float | None  # agreeing (decision, question) pairs / all such pairs
    question_agreement: dict[str, float]
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
    answers: dict[str, AnswerView]


class DecisionView(BaseModel):
    decision_id: str
    node: str
    ts: str
    fallback: bool
    state_preview: str
    calls: list[CallView]


def build_report(
    calls: Iterable[CallRecord], *, include_cold: bool = False, since: datetime | None = None
) -> StatsReport:
    by_node: dict[str, list[CallRecord]] = defaultdict(list)
    for call in calls:
        by_node[call.node].append(call)
    return StatsReport(
        generated_at=datetime.now(UTC).isoformat(),
        since=to_utc_iso(since) if since else None,
        include_cold=include_cold,
        nodes=[_node_stats(node, rows, include_cold) for node, rows in sorted(by_node.items())],
    )


def _node_stats(node: str, rows: list[CallRecord], include_cold: bool) -> NodeStats:
    decisions: dict[str, list[CallRecord]] = defaultdict(list)
    for row in rows:
        decisions[row.decision_id].append(row)

    compared = 0
    agreeing: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    for group in decisions.values():
        if any(c.fallback for c in group):
            continue
        primary = next((c for c in group if c.role == "primary" and c.answers is not None), None)
        shadow = next((c for c in group if c.role == "shadow" and c.answers is not None), None)
        if primary is None or shadow is None:
            continue
        assert primary.answers is not None and shadow.answers is not None
        compared += 1
        for question in primary.answers.keys() & shadow.answers.keys():
            totals[question] += 1
            agreeing[question] += answers_agree(
                [primary.answers[question], shadow.answers[question]]
            )

    all_pairs = sum(totals.values())
    return NodeStats(
        node=node,
        decisions=len(decisions),
        fallbacks=sum(any(c.fallback for c in group) for group in decisions.values()),
        compared=compared,
        agreement_rate=sum(agreeing.values()) / all_pairs if all_pairs else None,
        question_agreement={q: agreeing[q] / totals[q] for q in sorted(totals)},
        backends=[
            _backend_stats(name, [r for r in rows if r.backend == name], include_cold)
            for name in sorted({r.backend for r in rows})
        ],
    )


def _backend_stats(backend: str, rows: list[CallRecord], include_cold: bool) -> BackendStats:
    ok = [r for r in rows if r.error is None]
    latencies = [r.latency_ms for r in ok if include_cold or not r.cold]
    return BackendStats(
        backend=backend,
        calls=len(rows),
        errors=len(rows) - len(ok),
        cold_calls=sum(r.cold for r in rows),
        used_calls=sum(r.used for r in rows),
        latency_ms=LatencyStats(
            p50=percentile(latencies, 0.5), p95=percentile(latencies, 0.95), mean=_mean(latencies)
        ),
        mean_input_tokens=_mean([r.input_tokens for r in ok if r.input_tokens is not None]),
        mean_output_tokens=_mean([r.output_tokens for r in ok if r.output_tokens is not None]),
        mean_confidence=_mean([r.mean_confidence for r in ok if r.mean_confidence is not None]),
    )


def recent_decisions(calls: Iterable[CallRecord]) -> list[DecisionView]:
    """Group calls by decision, newest decision first."""
    groups: dict[str, list[CallRecord]] = defaultdict(list)
    for call in calls:
        groups[call.decision_id].append(call)
    views = [
        DecisionView(
            decision_id=decision_id,
            node=group[0].node,
            ts=min(c.ts for c in group),
            fallback=any(c.fallback for c in group),
            state_preview=group[0].state_preview,
            calls=[_call_view(c) for c in sorted(group, key=lambda c: c.role != "primary")],
        )
        for decision_id, group in groups.items()
    ]
    return sorted(views, key=lambda v: v.ts, reverse=True)


def _call_view(call: CallRecord) -> CallView:
    answers = call.answers or {}
    return CallView(
        backend=call.backend,
        role=call.role,
        used=call.used,
        cold=call.cold,
        latency_ms=call.latency_ms,
        error=call.error,
        answers={
            q: AnswerView(verdict=answer_verdict(a), confidence=round(answer_confidence(a), 3))
            for q, a in answers.items()
        },
    )
