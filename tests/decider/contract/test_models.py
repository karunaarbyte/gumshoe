import pytest
from pydantic import ValidationError

from gumshoe.decider.contract.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    DecisionResult,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE


def test_request_serialises_with_type_tags():
    req = DecisionRequest(model="nimble", state=DEMO_STATE, questions=DEMO_QUESTIONS)
    dumped = req.model_dump(mode="json")
    assert dumped["model"] == "nimble"
    assert dumped["questions"]["intent"]["type"] == "choice"
    assert dumped["questions"]["needs_interrogation"]["type"] == "noul"
    assert dumped["questions"]["urgency"]["type"] == "score"
    assert dumped["questions"]["urgency"]["criteria"] == [
        "Mundane", "Mild", "Tense", "Dramatic", "Climactic",
    ]


def test_request_matches_captured_request_fixture(load_fixture):
    req = DecisionRequest(model="nimble", state=DEMO_STATE, questions=DEMO_QUESTIONS)
    assert req.model_dump(mode="json") == load_fixture("nimble_all_types.request.json")


def test_union_picks_class_from_type_field():
    req = DecisionRequest.model_validate(
        {
            "model": "m",
            "state": "s",
            "questions": {
                "a": {"type": "noul", "instructions": "?"},
                "b": {"type": "score", "instructions": "?", "criteria": ["lo", "hi"]},
                "c": {"type": "choice", "instructions": "?", "criteria": {"x": "1", "y": "2"}},
            },
        }
    )
    assert isinstance(req.questions["a"], NoulQuestion)
    assert isinstance(req.questions["b"], ScoreQuestion)
    assert isinstance(req.questions["c"], ChoiceQuestion)


@pytest.mark.parametrize("n_options", [1, 27])
def test_choice_option_count_is_bounded(n_options):
    criteria = {f"o{i}": "d" for i in range(n_options)}
    with pytest.raises(ValidationError):
        ChoiceQuestion(instructions="?", criteria=criteria)


def test_choice_accepts_boundaries():
    ChoiceQuestion(instructions="?", criteria={"a": "1", "b": "2"})
    ChoiceQuestion(instructions="?", criteria={f"o{i}": "d" for i in range(26)})


def test_score_needs_at_least_two_levels():
    with pytest.raises(ValidationError):
        ScoreQuestion(instructions="?", criteria=["only one"])


def test_request_needs_between_1_and_64_questions():
    q = NoulQuestion(instructions="?")
    with pytest.raises(ValidationError):
        DecisionRequest(model="m", state="s", questions={})
    with pytest.raises(ValidationError):
        DecisionRequest(model="m", state="s", questions={f"q{i}": q for i in range(65)})
    DecisionRequest(model="m", state="s", questions={f"q{i}": q for i in range(64)})


@pytest.mark.parametrize("state", ["", "   ", "\n\t"])
def test_blank_state_is_rejected(state):
    with pytest.raises(ValidationError):
        DecisionRequest(model="m", state=state, questions=DEMO_QUESTIONS)


def test_parses_real_nimble_response(load_fixture):
    result = DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))
    assert result.model == "nimble"
    assert isinstance(result.answers["intent"], ChoiceAnswer)
    assert isinstance(result.answers["needs_interrogation"], NoulAnswer)
    assert isinstance(result.answers["urgency"], ScoreAnswer)
    assert result.choice("intent").choice == "dialogue"
    assert sum(result.choice("intent").probabilities.values()) == pytest.approx(1.0, abs=0.01)
    assert result.noul("needs_interrogation").yes is True
    assert result.score("urgency").legend["0"] == "Mundane"
    assert result.usage is not None and result.usage.input_tokens > 0


def test_parses_real_jev_response(load_fixture):
    result = DecisionResult.model_validate(load_fixture("jev_all_types.response.json"))
    assert result.model.startswith("jev-")
    assert result.choice("intent").choice == "dialogue"
    assert result.noul("needs_interrogation").yes is True
    assert result.score("urgency").legend["4"] == "Climactic"
    assert result.usage is not None and result.usage.input_tokens > 0


def test_parses_jev_docs_example(load_fixture):
    result = DecisionResult.model_validate(load_fixture("jev_docs_example.response.json"))
    assert result.model == "jev-1.13.0"
    assert result.choice("department").choice == "technical"
    assert result.score("frustration").score == 1.0
    assert result.noul("is_urgent").yes is True


def test_unknown_fields_are_ignored(load_fixture):
    raw = load_fixture("nimble_all_types.response.json")
    raw["brand_new_field"] = {"x": 1}
    raw["answers"]["intent"]["extra"] = "ignored"
    DecisionResult.model_validate(raw)


def test_noul_threshold():
    assert NoulAnswer(type="noul", noul=0.5).yes is True
    assert NoulAnswer(type="noul", noul=0.49).yes is False


def test_accessor_with_wrong_type_raises_type_error(load_fixture):
    result = DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))
    with pytest.raises(TypeError, match="intent"):
        result.noul("intent")


def test_accessor_with_unknown_name_raises_key_error(load_fixture):
    result = DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))
    with pytest.raises(KeyError):
        result.choice("does_not_exist")
