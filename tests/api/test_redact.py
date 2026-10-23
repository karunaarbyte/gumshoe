import copy
import json

import pytest

from gumshoe.api.redact import (
    ANSWER_NODES,
    BLANKED_CALL_FIELDS,
    BLANKED_VIEW_FIELDS,
    FILTERED_CALL_FIELDS,
    FILTERED_VIEW_FIELDS,
    KEPT_CALL_FIELDS,
    KEPT_VIEW_FIELDS,
    for_player,
)
from gumshoe.stats.queries import AnswerView, CallView, DecisionView

SECRET = "LOCKEDNAME-XYZ"


def view(node, preview="the player typed: accuse Maud"):
    answer = AnswerView(verdict="suspect_3", confidence=0.9)
    call = CallView(
        backend="jev",
        role="primary",
        used=True,
        cold=False,
        latency_ms=300.0,
        error=None,
        input_tokens=1000,
        output_tokens=5,
        est_cost_usd=0.0,
        answers={"who": answer},
    )
    return DecisionView(
        decision_id="d1",
        node=node,
        ts="t",
        fallback=False,
        state_preview=preview,
        calls=[call],
        agrees={"who": True},
    )


def test_the_typed_text_is_removed():
    assert for_player(view("understand")).state_preview == ""


def test_understand_answers_are_kept():
    out = for_player(view("understand"))
    assert out.calls[0].answers.keys() == {"who"} and out.calls[0].input_tokens == 1000


def test_accusation_answers_are_removed_everything_else_kept():
    out = for_player(view("parse_accusation"))
    assert (
        out.calls[0].answers == {}
        and out.calls[0].latency_ms == 300.0
        and out.agrees == {"who": True}
    )


def test_the_original_is_not_changed():
    original = view("parse_accusation")
    before = copy.deepcopy(original)
    out = for_player(original)
    assert original == before
    assert original.state_preview != "" and original.calls[0].answers
    assert out is not original and out.calls[0] is not original.calls[0]


def test_the_original_is_not_changed_for_a_kept_node():
    original = view("understand")
    before = copy.deepcopy(original)
    out = for_player(original)
    assert original == before
    assert out.calls[0].answers["who"] is not original.calls[0].answers["who"]


# --- allow-list: every field of the views is consciously classified ----------------------------


def test_the_decision_fields_are_all_classified():
    assert set(KEPT_VIEW_FIELDS) == {"decision_id", "node", "ts", "fallback"}
    assert set(FILTERED_VIEW_FIELDS) == {"calls", "agrees"}
    assert set(BLANKED_VIEW_FIELDS) == {"state_preview"}
    # a new DecisionView field fails here until it is put in one of the three sets
    assert set(DecisionView.model_fields) == (
        KEPT_VIEW_FIELDS | FILTERED_VIEW_FIELDS | BLANKED_VIEW_FIELDS
    )


def test_the_call_fields_are_all_classified():
    assert set(KEPT_CALL_FIELDS) == {
        "backend",
        "role",
        "used",
        "cold",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "est_cost_usd",
    }
    assert set(FILTERED_CALL_FIELDS) == {"answers", "error"}
    assert not BLANKED_CALL_FIELDS
    # a new CallView field fails here until it is put in one of the three sets
    assert set(CallView.model_fields) == (
        KEPT_CALL_FIELDS | FILTERED_CALL_FIELDS | BLANKED_CALL_FIELDS
    )


def test_the_answer_fields_are_known():
    # verdict is filtered to a safe token, confidence is a number
    assert set(AnswerView.model_fields) == {"verdict", "confidence"}


def test_only_known_nodes_keep_answers():
    assert set(ANSWER_NODES) == {"understand", "post_check"}
    assert for_player(view("some_future_node")).calls[0].answers == {}


# --- the secret never reaches the player --------------------------------------------------------

# the string fields copied verbatim: server-made (an id, a timestamp, a node name, the configured
# backend name and its role), never model or player text
VERBATIM_STRINGS = {"decision_id", "ts", "node", "backend", "role"}


def secret_view(node: str) -> DecisionView:
    """Every string field the player could be shown holds the secret, except the verbatim ones."""
    answer = AnswerView(verdict=f"{SECRET} did it", confidence=0.5)
    call = CallView(
        backend="jev",
        role="shadow",
        used=False,
        cold=True,
        latency_ms=1.0,
        error=f"HTTP 500: the prompt said {SECRET} is the killer",
        input_tokens=1,
        output_tokens=1,
        est_cost_usd=None,
        answers={"who": answer, f"is {SECRET} guilty": AnswerView(verdict="yes", confidence=1)},
    )
    return DecisionView(
        decision_id="d1",
        node=node,
        ts="2026-10-23T00:00:00Z",
        fallback=True,
        state_preview=f"locked suspects: {SECRET}",
        calls=[call],
        agrees={f"is {SECRET} guilty": True, "who": False},
    )


def test_the_verbatim_strings_are_exactly_the_kept_string_fields():
    strings = {
        name
        for model, kept in ((DecisionView, KEPT_VIEW_FIELDS), (CallView, KEPT_CALL_FIELDS))
        for name, info in model.model_fields.items()
        if name in kept and info.annotation is str
    }
    assert strings == VERBATIM_STRINGS


@pytest.mark.parametrize("node", ["understand", "post_check", "parse_accusation", "other"])
def test_the_secret_is_absent_from_the_player_view(node):
    original = secret_view(node)
    assert SECRET in json.dumps(original.model_dump())  # the fixture really holds it
    out = for_player(original)
    assert SECRET not in json.dumps(out.model_dump())


def test_an_unsafe_verdict_or_question_name_is_dropped_a_safe_one_kept():
    out = for_player(secret_view("understand"))
    assert out.calls[0].answers == {}
    assert out.agrees == {"who": False}


@pytest.mark.parametrize("verdict", ["suspect_3", "place_1", "none", "yes", "no", "2.00"])
def test_the_verdict_shapes_the_game_makes_are_kept(verdict):
    v = view("understand")
    v.calls[0].answers["who"] = AnswerView(verdict=verdict, confidence=0.4)
    assert for_player(v).calls[0].answers["who"].verdict == verdict


@pytest.mark.parametrize("verdict", ["Maud", "Maud Pell", "suspect 3", "", "x" * 41])
def test_other_verdicts_are_dropped(verdict):
    v = view("understand")
    v.calls[0].answers["who"] = AnswerView(verdict=verdict, confidence=0.4)
    assert for_player(v).calls[0].answers == {}


def test_an_error_becomes_a_plain_marker():
    v = view("understand")
    v.calls[0].error = "DeciderAPIError (jev, HTTP 500)"
    assert for_player(v).calls[0].error == "failed"
    assert for_player(view("understand")).calls[0].error is None
