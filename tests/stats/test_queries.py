from datetime import UTC, datetime

import pytest

from gumshoe.decider import ScoreAnswer
from gumshoe.stats.queries import Price, build_report, disagreeing, percentile, recent_decisions
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
    assert nimble.error_latency_ms.p95 == 30000  # it is reported beside it instead
    assert backend(build_report(pair("d1")).nodes[0], "nimble").error_latency_ms.p95 is None


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


def test_a_decision_with_no_shared_questions_is_not_counted_as_compared():
    a = make_record(decision_id="d", backend="jev", answers={"only_jev": choice("x")})
    b = make_record(
        decision_id="d",
        backend="nimble",
        role="shadow",
        used=False,
        answers={"only_nimble": choice("x")},
    )
    [node] = build_report([a, b]).nodes
    assert node.decisions == 1
    assert node.compared == 0 and node.agreement_rate is None


def test_error_latency_follows_the_cold_rule():
    failed = make_record(
        decision_id="d2",
        backend="nimble",
        role="shadow",
        used=False,
        cold=True,
        error="[nimble] timed out",
        answers=None,
        latency_ms=30000,
    )
    calls = [*pair("d1"), failed]
    assert backend(build_report(calls).nodes[0], "nimble").error_latency_ms.p95 is None
    nimble = backend(build_report(calls, include_cold=True).nodes[0], "nimble")
    assert nimble.error_latency_ms.p95 == 30000


# --- cost, bands, confusion, disagreement --------------------------------------------------------

PRICES = {"jev": Price(usd_per_mtok_in=2.0, usd_per_mtok_out=10.0)}


def test_cost_is_estimated_from_the_prices_and_the_token_totals():
    [node] = build_report(pair("d1") + pair("d2"), prices=PRICES).nodes
    jev, nimble = backend(node, "jev"), backend(node, "nimble")
    assert (jev.total_input_tokens, jev.total_output_tokens) == (800, 160)
    assert jev.est_cost_usd == 0.0032  # (800 * 2 + 160 * 10) / 1e6
    assert (nimble.total_input_tokens, nimble.est_cost_usd) == (2000, 0.0)  # no price: free


def test_each_call_shows_its_tokens_and_cost():
    [view] = recent_decisions(pair("d1"), prices=PRICES)
    jev, nimble = view.calls
    assert (jev.input_tokens, jev.output_tokens, jev.est_cost_usd) == (400, 80, 0.0016)
    assert nimble.est_cost_usd == 0.0


def test_a_call_that_reported_no_tokens_has_no_cost_estimate():
    row = make_record(input_tokens=None, output_tokens=None)
    [view] = recent_decisions([row], prices=PRICES)
    [jev] = build_report([row], prices=PRICES).nodes[0].backends
    assert view.calls[0].est_cost_usd is None
    assert (jev.total_input_tokens, jev.est_cost_usd) == (0, 0.0)


@pytest.mark.parametrize(
    ("jev_p", "nimble_p", "agree"),
    [
        (0.55, 0.9, False),  # both "yes" at 0.5, but the game would ask again on one of them
        (0.1, 0.45, False),  # both "no" at 0.5, but one is a cancel and one is unsure
        (0.85, 0.95, True),
        (0.8, 1.0, True),  # the yes band is inclusive
        (0.4, 0.6, True),  # both unsure
    ],
)
def test_confirms_pending_agrees_by_the_games_bands(jev_p, nimble_p, agree):
    a = make_record(decision_id="d", answers={"confirms_pending": noul(jev_p)})
    b = make_record(
        decision_id="d",
        backend="nimble",
        role="shadow",
        used=False,
        answers={"confirms_pending": noul(nimble_p)},
    )
    [node] = build_report([a, b]).nodes
    assert node.question_agreement == {"confirms_pending": 1.0 if agree else 0.0}


def test_other_yes_no_questions_still_agree_at_one_half():
    a = make_record(decision_id="d", answers={"needs": noul(0.55)})
    b = make_record(
        decision_id="d", backend="nimble", role="shadow", used=False, answers={"needs": noul(0.9)}
    )
    assert build_report([a, b]).nodes[0].question_agreement == {"needs": 1.0}


def test_the_intent_confusion_matrix_counts_primary_against_shadow():
    calls = (
        pair("d1", jev="action", nimble="action")
        + pair("d2", jev="action", nimble="meta")
        + pair("d3", jev="meta", nimble="meta")
        + pair("d4", jev="action", nimble="x", fallback=True)  # not a head-to-head
    )
    [node] = build_report(calls).nodes
    assert node.intent_confusion == {"action": {"action": 1, "meta": 1}, "meta": {"meta": 1}}


def test_a_node_without_an_intent_question_has_an_empty_matrix():
    a = make_record(decision_id="d", answers={"needs": noul(0.9)})
    b = make_record(
        decision_id="d", backend="nimble", role="shadow", used=False, answers={"needs": noul(0.9)}
    )
    assert build_report([a, b]).nodes[0].intent_confusion == {}


def test_the_per_question_agreement_comes_before_the_pooled_rate():
    [node] = build_report(pair("d1")).nodes
    keys = list(node.model_dump())
    assert keys.index("question_agreement") < keys.index("agreement_rate")


def test_disagreeing_keeps_only_head_to_heads_that_differ():
    calls = (
        pair("same", jev="a", nimble="a")
        + pair("differ", jev="a", nimble="b")
        + pair("fell_back", jev="a", nimble="b", fallback=True)
    )
    assert {c.decision_id for c in disagreeing(calls)} == {"differ"}
    assert len(disagreeing(calls)) == 2  # both rows of that decision


def test_a_failed_call_that_reported_tokens_still_counts_toward_the_cost():
    failed = make_record(error="[jev] could not parse response", answers=None, output_tokens=0)
    [jev] = build_report([failed], prices=PRICES).nodes[0].backends
    assert (jev.total_input_tokens, jev.est_cost_usd) == (400, 0.0008)


def _gate_pair():
    a = make_record(decision_id="d", answers={"confirms_pending": noul(0.85)})
    b = make_record(
        decision_id="d",
        backend="nimble",
        role="shadow",
        used=False,
        answers={"confirms_pending": noul(0.5)},
    )
    return [a, b]


def test_the_confirmation_bands_follow_the_configured_gate():
    calls = _gate_pair()
    assert build_report(calls).nodes[0].question_agreement == {"confirms_pending": 0.0}
    strict = build_report(calls, confirm_gate=0.9).nodes[0]
    assert strict.question_agreement == {"confirms_pending": 1.0}  # 0.85 is unsure at 0.9
    assert len(disagreeing(calls)) == 2
    assert disagreeing(calls, confirm_gate=0.9) == []


# --- the stats page's honesty: weight bands, shadow errors, roles, per-question agreement --------


def score(value):
    return ScoreAnswer(type="score", score=value, legend={}, probabilities={}, confidence=0.5)


def weighed(decision_id, a, b, *, intent="search", ts="2026-10-01T10:00:00.000000+00:00"):
    """A understand-like decision with an intent and a weight on each side."""
    return [
        make_record(
            decision_id=decision_id,
            ts=ts,
            backend="jev",
            answers={"intent": choice(intent), "weight": score(a)},
        ),
        make_record(
            decision_id=decision_id,
            ts=ts,
            backend="nimble",
            role="shadow",
            used=False,
            answers={"intent": choice(intent), "weight": score(b)},
        ),
    ]


def shadow_failed(decision_id, intent="search"):
    return [
        make_record(decision_id=decision_id, answers={"intent": choice(intent)}),
        make_record(
            decision_id=decision_id,
            backend="nimble",
            role="shadow",
            used=False,
            error="DeciderConnectionError (nimble)",
            answers=None,
            latency_ms=30000.0,
        ),
    ]


@pytest.mark.parametrize(
    ("a", "b", "agree"),
    [(2.4, 2.6, False), (1.0, 1.9, True), (3.0, 3.9, True), (2.5, 2.5, True), (2.49, 2.5, False)],
)
def test_weight_agrees_when_both_sit_on_the_same_side_of_the_dramatic_threshold(a, b, agree):
    # the game only acts on weight as a band (the dramatic persona from 2.5), so that is the
    # agreement that matters; two scores a constant offset apart are not a different judgment
    [node] = build_report(weighed("d", a, b)).nodes
    assert node.question_agreement["weight"] == (1.0 if agree else 0.0)


def test_the_weight_threshold_follows_the_configured_dramatic_from():
    [node] = build_report(weighed("d", 2.6, 2.9), dramatic_from=3.0).nodes
    assert node.question_agreement["weight"] == 1.0
    [node] = build_report(weighed("d", 2.6, 3.1), dramatic_from=3.0).nodes
    assert node.question_agreement["weight"] == 0.0


def test_other_score_questions_keep_the_half_level_tolerance():
    [node] = build_report(weighed("d", 1.0, 1.4)).nodes
    # only `weight` is banded; the generic score rule is covered by the urgency test above
    assert node.question_agreement["weight"] == 1.0


def test_the_mean_signed_score_offset_shows_a_constant_bias():
    calls = weighed("d1", 1.0, 2.0) + weighed("d2", 2.0, 2.6)
    [node] = build_report(calls).nodes
    assert node.score_offset == {"weight": pytest.approx(0.8)}  # shadow minus primary


def test_a_shadow_error_is_counted_and_the_decision_is_not_compared():
    calls = shadow_failed("e1") + shadow_failed("e2") + weighed("ok", 1.0, 1.0)
    [node] = build_report(calls).nodes
    assert (node.decisions, node.compared, node.shadow_errors) == (3, 1, 2)


def test_a_fallback_is_not_a_shadow_error():
    calls = pair("f", jev="a", nimble="b", fallback=True)
    [node] = build_report(calls).nodes
    assert node.shadow_errors == 0 and node.fallbacks == 1


def test_the_confusion_matrix_has_an_error_column_for_decisions_the_shadow_missed():
    calls = (
        shadow_failed("e1", "search")
        + shadow_failed("e2", "search")
        + pair("ok", jev="search", nimble="records")
    )
    [node] = build_report(calls).nodes
    assert node.intent_confusion == {"search": {"(error)": 2, "records": 1}}


def test_each_backend_reports_the_role_it_played():
    [node] = build_report(pair("d")).nodes
    assert backend(node, "jev").role == "primary" and backend(node, "nimble").role == "shadow"


def test_a_decision_view_says_which_questions_agree_by_the_servers_own_rule():
    [view] = recent_decisions(weighed("d", 2.4, 2.6))  # differ by a band: weight disagrees
    assert view.agrees == {"intent": True, "weight": False}
    [view] = recent_decisions(weighed("d", 1.0, 1.9))  # 0.9 apart but the same band: agrees
    assert view.agrees == {"intent": True, "weight": True}


def test_a_decision_that_is_not_a_head_to_head_has_no_agreement_flags():
    [view] = recent_decisions(shadow_failed("e"))
    assert view.agrees == {}
    [view] = recent_decisions(pair("f", jev="a", nimble="b", fallback=True))
    assert view.agrees == {}


def test_disagreeing_can_be_narrowed_to_one_question():
    def two(decision_id, intent_a, intent_b, weight_a, weight_b):
        ts = "2026-10-01T10:00:00.000000+00:00"
        return [
            make_record(
                decision_id=decision_id,
                ts=ts,
                answers={"intent": choice(intent_a), "weight": score(weight_a)},
            ),
            make_record(
                decision_id=decision_id,
                ts=ts,
                backend="nimble",
                role="shadow",
                used=False,
                answers={"intent": choice(intent_b), "weight": score(weight_b)},
            ),
        ]

    calls = two("weight_only", "a", "a", 2.4, 2.6) + two("intent_only", "a", "b", 1.0, 1.0)
    assert {c.decision_id for c in disagreeing(calls, question="weight")} == {"weight_only"}
    assert {c.decision_id for c in disagreeing(calls, question="intent")} == {"intent_only"}
    assert {c.decision_id for c in disagreeing(calls)} == {"weight_only", "intent_only"}
