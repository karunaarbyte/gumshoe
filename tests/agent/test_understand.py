import pytest

from gumshoe.agent.understand import (
    INTENTS,
    NO_TARGET,
    build_understand,
    read_intent,
)
from gumshoe.cases import PlayerCaseView
from gumshoe.cases.play.views import LocationView, SuspectView
from gumshoe.decider import DecisionResult
from tests.agent.fakes import choice, criteria_of, noul, score, understand_answers


def brief():
    return PlayerCaseView(
        intro="i",
        locations=(
            LocationView(number=1, handle="h_l1", name="Cellar", description="d", locked=False),
        ),
        suspects=(
            SuspectView(number=1, handle="h_s1", name="Berta", description="d", locked=False),
            SuspectView(number=2, handle="h_s2", name="Piers", description="d", locked=True),
        ),
        record_kinds=(),
        attempts_left=3,
        status="playing",
    )


def test_the_batch_has_intent_target_and_weight_and_confirms_only_when_pending():
    plain = build_understand(brief(), pending=False)
    assert set(plain.questions) == {"intent", "target", "weight"}
    pending = build_understand(brief(), pending=True)
    assert set(pending.questions) == {"intent", "target", "weight", "confirms_pending"}


def test_intent_options_are_the_documented_nine():
    q = build_understand(brief(), pending=False).questions["intent"]
    assert list(criteria_of(q)) == list(INTENTS)
    assert set(INTENTS) == {
        "search", "interrogate", "records", "talk", "accuse",
        "notebook", "give_up", "meta", "other",
    }  # fmt: skip


def test_target_options_are_places_and_suspects_by_number_plus_none():
    built = build_understand(brief(), pending=False)
    assert list(criteria_of(built.questions["target"])) == [
        "place_1",
        "suspect_1",
        "suspect_2",
        NO_TARGET,
    ]
    assert built.targets == {"place_1": "h_l1", "suspect_1": "h_s1", "suspect_2": "h_s2"}
    assert "Cellar" in criteria_of(built.questions["target"])["place_1"]


def test_too_many_targets_fail_loudly():
    many = brief().model_copy(
        update={
            "locations": tuple(
                LocationView(
                    number=i, handle=f"h_l{i}", name=f"P{i}", description="d", locked=False
                )
                for i in range(1, 27)
            )
        }
    )
    with pytest.raises(ValueError, match="26"):
        build_understand(many, pending=False)


def test_read_intent_maps_keys_to_handles_and_reads_scores_and_confirmation():
    built = build_understand(brief(), pending=True)
    answers = understand_answers(
        built.questions,
        intent="interrogate",
        target="suspect_2",
        intent_p=0.8,
        target_p=0.7,
        weight=3.2,
        confirm=0.9,
    )
    intent = read_intent(DecisionResult(model="m", answers=answers), built.targets)
    assert (intent.name, intent.target) == ("interrogate", "h_s2")
    assert (intent.intent_confidence, intent.target_confidence) == (0.8, 0.7)
    assert intent.weight == 3.2 and intent.confirms_pending == 0.9


def test_none_target_and_unknown_keys_read_as_no_target_and_unknown_intent_as_other():
    built = build_understand(brief(), pending=False)
    answers = understand_answers(built.questions, intent="search", target=NO_TARGET)
    assert read_intent(DecisionResult(model="m", answers=answers), built.targets).target is None
    odd = {
        "intent": choice(["bogus", "x"], "bogus"),
        "target": choice(["nope", "y"], "nope"),
        "weight": score(1.0),
    }
    intent = read_intent(DecisionResult(model="m", answers=odd), built.targets)
    assert intent.name == "other" and intent.target is None


def test_a_missing_answer_raises_key_error_for_the_caller_to_treat_as_a_failed_decision():
    built = build_understand(brief(), pending=False)
    with pytest.raises(KeyError):
        read_intent(
            DecisionResult(model="m", answers={"intent": choice(["a", "b"], "a")}),
            built.targets,
        )
    with pytest.raises(TypeError):
        read_intent(
            DecisionResult(
                model="m",
                answers={"intent": noul(0.5), "target": noul(0.5), "weight": noul(0.5)},
            ),
            built.targets,
        )
