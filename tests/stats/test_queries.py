from datetime import UTC, datetime

import pytest

from gumshoe.decider import ScoreAnswer
from gumshoe.stats.queries import build_report, percentile, recent_decisions
from tests.stats.factories import choice, make_record, noul


def pair(
    decision_id,
    *,
    node="intent",
    jev="dialogue",
    nimble="dialogue",
    jev_ms=500.0,
    nimble_ms=1000.0,
    nimble_cold=False,
    fallback=False,
    ts="2026-10-01T10:00:00.000000+00:00",
):
    return [
        make_record(
            decision_id=decision_id,
            node=node,
            backend="jev",
            role="primary",
            used=True,
            latency_ms=jev_ms,
            answers={"intent": choice(jev)},
            ts=ts,
            fallback=fallback,
        ),
        make_record(
            decision_id=decision_id,
            node=node,
            backend="nimble",
            role="shadow",
            used=False,
            latency_ms=nimble_ms,
            cold=nimble_cold,
            answers={"intent": choice(nimble)},
            ts=ts,
            fallback=fallback,
            input_tokens=1000,
            output_tokens=4,
        ),
    ]


def backend(node, name):
    return next(b for b in node.backends if b.backend == name)


def test_percentile_uses_nearest_rank():
    values = list(range(1, 11))
    assert percentile(values, 0.5) == 5
    assert percentile(values, 0.95) == 10
    assert percentile(values, 0.0) == 1
    assert percentile(values, 1.0) == 10
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.5) is None
    assert percentile([3, 1, 2], 0.5) == 2  # input need not be sorted


def test_empty_input_gives_an_empty_report():
    report = build_report([], include_cold=False)
    assert report.nodes == []
    assert report.include_cold is False


def test_per_backend_counts_latency_tokens_and_confidence():
    calls = [
        r
        for i, ms in enumerate([100, 200, 300, 400])
        for r in pair(f"d{i}", jev_ms=ms, nimble_ms=ms * 2)
    ]
    [node] = build_report(calls).nodes
    jev, nimble = backend(node, "jev"), backend(node, "nimble")
    assert (jev.calls, jev.errors, jev.cold_calls, jev.used_calls) == (4, 0, 0, 4)
    assert jev.latency_ms.p50 == 200 and jev.latency_ms.p95 == 400 and jev.latency_ms.mean == 250
    assert nimble.latency_ms.p50 == 400 and nimble.used_calls == 0
    assert jev.mean_input_tokens == 400 and nimble.mean_input_tokens == 1000
    assert nimble.mean_output_tokens == 4
    assert jev.mean_confidence == pytest.approx(0.9)
    assert node.decisions == 4


def test_cold_calls_are_excluded_from_latency_unless_asked():
    calls = (
        pair("d1", nimble_ms=4000, nimble_cold=True)
        + pair("d2", nimble_ms=600)
        + pair("d3", nimble_ms=700)
    )
    nimble = backend(build_report(calls).nodes[0], "nimble")
    assert nimble.cold_calls == 1 and nimble.calls == 3
    assert nimble.latency_ms.p95 == 700  # the 4000 ms cold call is left out
    nimble = backend(build_report(calls, include_cold=True).nodes[0], "nimble")
    assert nimble.latency_ms.p95 == 4000


def test_a_backend_with_only_cold_calls_has_no_latency_by_default():
    nimble = backend(build_report(pair("d1", nimble_cold=True)).nodes[0], "nimble")
    assert nimble.calls == 1 and nimble.cold_calls == 1
    assert nimble.latency_ms.p50 is None and nimble.latency_ms.mean is None


def test_errored_calls_are_counted_but_not_measured():
    failed = make_record(
        decision_id="d2",
        backend="nimble",
        role="shadow",
        used=False,
        error="[nimble] down",
        answers=None,
        latency_ms=30000,
        input_tokens=None,
        output_tokens=None,
        mean_confidence=None,
        min_confidence=None,
    )
    nimble = backend(build_report([*pair("d1"), failed]).nodes[0], "nimble")
    assert nimble.calls == 2 and nimble.errors == 1
    assert nimble.latency_ms.p95 == 1000  # the 30 s failure is not a latency sample


def test_node_whose_calls_all_failed_has_no_numbers_and_no_agreement():
    failed = make_record(
        decision_id="d1",
        error="[jev] down",
        answers=None,
        mean_confidence=None,
        min_confidence=None,
        input_tokens=None,
        output_tokens=None,
    )
    [node] = build_report([failed]).nodes
    [jev] = node.backends
    assert jev.errors == 1 and jev.latency_ms.p50 is None and jev.mean_confidence is None
    assert node.agreement_rate is None and node.compared == 0


def test_agreement_rate_counts_questions_across_compared_decisions():
    calls = (
        pair("d1", jev="action", nimble="action")
        + pair("d2", jev="action", nimble="action")
        + pair("d3", jev="action", nimble="action")
        + pair("d4", jev="action", nimble="meta")
    )
    [node] = build_report(calls).nodes
    assert node.compared == 4
    assert node.agreement_rate == 0.75
    assert node.question_agreement == {"intent": 0.75}


def test_fallback_decisions_are_counted_but_not_compared():
    calls = pair("d1") + pair("d2", fallback=True, jev="a", nimble="b")
    [node] = build_report(calls).nodes
    assert node.decisions == 2 and node.fallbacks == 1
    assert node.compared == 1 and node.agreement_rate == 1.0


def test_decision_with_one_backend_is_not_compared():
    [node] = build_report([make_record(decision_id="solo")]).nodes
    assert node.compared == 0 and node.agreement_rate is None


def test_scores_agree_within_the_tolerance_not_by_rounding():
    def score(value):
        return ScoreAnswer(type="score", score=value, legend={}, probabilities={}, confidence=0.5)

    def decision(decision_id, a, b):
        return [
            make_record(decision_id=decision_id, backend="jev", answers={"urgency": score(a)}),
            make_record(
                decision_id=decision_id,
                backend="nimble",
                role="shadow",
                used=False,
                answers={"urgency": score(b)},
            ),
        ]

    close = build_report(decision("d1", 1.0, 1.4)).nodes[0]
    far = build_report(decision("d2", 1.0, 1.5)).nodes[0]
    assert close.agreement_rate == 1.0 and far.agreement_rate == 0.0


def test_agreement_only_looks_at_questions_both_backends_answered():
    a = make_record(
        decision_id="d", backend="jev", answers={"intent": choice("x"), "extra": noul(0.9)}
    )
    b = make_record(
        decision_id="d",
        backend="nimble",
        role="shadow",
        used=False,
        answers={"intent": choice("x")},
    )
    [node] = build_report([a, b]).nodes
    assert node.question_agreement == {"intent": 1.0}


def test_agreement_is_across_questions_so_one_decision_can_partly_agree():
    both = {"intent": choice("x"), "needs": noul(0.9)}
    other = {"intent": choice("x"), "needs": noul(0.1)}
    a = make_record(decision_id="d", backend="jev", answers=both)
    b = make_record(decision_id="d", backend="nimble", role="shadow", used=False, answers=other)
    [node] = build_report([a, b]).nodes
    assert node.question_agreement == {"intent": 1.0, "needs": 0.0}
    assert node.agreement_rate == 0.5


def test_nodes_are_reported_separately_and_sorted():
    calls = pair("d1", node="route") + pair("d2", node="intent")
    assert [n.node for n in build_report(calls).nodes] == ["intent", "route"]


def test_report_echoes_its_parameters():
    since = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    report = build_report([], include_cold=True, since=since)
    assert report.include_cold is True
    assert report.since == "2026-10-01T09:00:00.000000+00:00"
    assert report.generated_at.endswith("+00:00")


def test_recent_decisions_group_calls_newest_first():
    calls = pair("old", ts="2026-10-01T10:00:00.000000+00:00", jev="a", nimble="a") + pair(
        "new", ts="2026-10-01T11:00:00.000000+00:00", jev="b", nimble="c", fallback=True
    )
    views = recent_decisions(calls)
    assert [v.decision_id for v in views] == ["new", "old"]
    new = views[0]
    assert new.fallback is True and new.node == "intent" and new.state_preview == "hello"
    by_backend = {c.backend: c for c in new.calls}
    assert by_backend["jev"].answers["intent"].verdict == "b"
    assert by_backend["jev"].answers["intent"].confidence == 0.9
    assert by_backend["nimble"].answers["intent"].verdict == "c"
    assert by_backend["jev"].used is True and by_backend["nimble"].used is False
    assert recent_decisions([]) == []


def test_recent_decisions_list_the_primary_call_first():
    shuffled = list(reversed(pair("d1")))  # shadow row before primary row
    [view] = recent_decisions(shuffled)
    assert [c.role for c in view.calls] == ["primary", "shadow"]


def test_recent_decision_with_a_failed_call_shows_the_error_and_no_answers():
    failed = make_record(decision_id="d1", error="[jev] timed out", answers=None, used=False)
    [view] = recent_decisions([failed])
    [call] = view.calls
    assert call.error == "[jev] timed out" and call.answers == {}


def test_agreement_does_not_depend_on_row_order():
    rows = pair("d1", jev="action", nimble="meta") + pair("d2", jev="x", nimble="x")
    forward = build_report(rows).nodes[0]
    backward = build_report(list(reversed(rows))).nodes[0]
    assert forward.agreement_rate == backward.agreement_rate == 0.5
    assert forward.compared == backward.compared == 2


def test_report_echoes_since_normalised_to_utc():
    naive = datetime(2026, 10, 1, 9, 0)
    assert build_report([], since=naive).since == "2026-10-01T09:00:00.000000+00:00"
    from datetime import timedelta, timezone

    plus_two = datetime(2026, 10, 1, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    assert build_report([], since=plus_two).since == "2026-10-01T09:00:00.000000+00:00"
