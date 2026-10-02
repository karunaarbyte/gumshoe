import pytest

from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.labels import candidate_forms, hedged, match_label
from tests.cases.fixtures import build_case

IX = CaseIndex.of(build_case())


def test_forms_are_label_aliases_and_the_display_name_for_suspects():
    assert candidate_forms(IX, Axis.WHO, "s_boris") == (
        "Boris the steward",
        "Boris",
        "the steward",
        "Boris",
    )
    assert candidate_forms(IX, Axis.HOW, "m_poison") == (
        "poisoned in the wine",
        "laced wine",
        "poison",
    )


@pytest.mark.parametrize(
    ("axis", "text", "expected"),
    [
        (Axis.WHO, "I accuse Boris", "s_boris"),
        (Axis.WHO, "the steward did it", "s_boris"),
        (Axis.WHO, "BORIS THE STEWARD", "s_boris"),
        (Axis.HOW, "he used poison", "m_poison"),
        (Axis.HOW, "poisoned the wine", "m_poison"),
        (Axis.HOW, "with a rope", "m_rope"),
        (Axis.WHY, "because of the debt", "v_debt"),
    ],
)
def test_clear_affirmative_text_resolves(axis, text, expected):
    assert match_label(IX, axis, text) == expected


@pytest.mark.parametrize(
    ("axis", "text"),
    [
        (Axis.WHO, "it wasn't Boris"),
        (Axis.WHO, "not Boris"),
        (Axis.WHO, "maybe the steward"),
        (Axis.WHO, "was it Boris?"),
        (Axis.WHO, "Boris or Clara"),
        (Axis.WHO, "I think Anna"),
        (Axis.WHO, ""),
        (Axis.WHO, "the"),
        (Axis.WHO, "somebody else"),
        (Axis.WHO, "it wasnt Boris"),
        (Axis.WHO, "Boris didnt do it"),
        (Axis.WHO, "Boris isnt the killer"),
        (Axis.WHO, "I doubt it was Boris"),
        (Axis.WHO, "hardly Boris"),
        (Axis.WHO, "Boris is unlikely"),
        (Axis.HOW, "wasnt poison"),
        (Axis.HOW, "it was not the poison"),
        (Axis.HOW, "poison or rope"),
        (Axis.WHY, "no idea"),
    ],
)
def test_hedged_negated_ambiguous_or_empty_text_never_resolves(axis, text):
    assert match_label(IX, axis, text) is None


def test_hedged_flags_questions_negations_and_hedge_words():
    assert hedged("was it Boris?") and hedged("it wasn't me") and hedged("maybe Anna")
    assert not hedged("Boris did it")
