import pytest

from gumshoe.cases.core.enums import FixStage
from gumshoe.cases.core.labels import distinctive, overlap_kind, token_set


def test_token_set_unions_texts():
    combined = token_set("poisoned wine", "laced drink")
    assert {"poison", "wine", "drink"} <= combined
    assert token_set("poisoned wine") <= combined


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("poisoned wine", "Poisoned  wine!", "equal"),
        ("poison", "poisoned wine", "subset"),
        ("poisoned wine", "wine", "subset"),
        ("stab", "stabbed with a dagger", "subset"),
        ("poison dart", "poison", "subset"),
        ("strangled with a rope", "struck with a candlestick", None),
        ("out of jealousy", "to claim an inheritance", None),
        ("", "poison", None),
    ],
)
def test_overlap_kind(a, b, expected):
    assert overlap_kind(a, b) == expected


def test_substring_overlap_when_tokens_differ():
    # "candle" is not a stem-equal token of "candlestick", but it is contained in it
    assert overlap_kind("candle", "candlestick") == "substring"


def test_distinctive_tokens_remove_those_shared_with_others():
    own = frozenset({"struck", "dagger"})
    others = [frozenset({"struck", "candlestick"}), frozenset({"rope"})]
    assert distinctive(own, others) == frozenset({"dagger"})
    assert distinctive(own, []) == own


def test_fix_stage_members():
    assert {s.value for s in FixStage} == {
        "roster",
        "truth",
        "timeline",
        "facts",
        "placement",
        "gating",
        "skin",
        "assemble",
        "pack",
        "none",
    }
