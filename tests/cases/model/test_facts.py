import pytest
from pydantic import ValidationError

from gumshoe.cases.model.entities import Claim, Effect, Fact, SourceRef
from gumshoe.cases.model.enums import (
    Axis,
    ClaimKind,
    EffectKind,
    FactKind,
    Origin,
    RecordSubjectType,
    SourceKind,
)


def search(loc="l_study"):
    return SourceRef(kind=SourceKind.SEARCH, target=loc)


def test_enum_values_are_the_pinned_strings():
    assert [a.value for a in Axis] == ["who", "how", "why"]
    assert [e.value for e in EffectKind] == ["rules_out", "supports", "proves"]
    assert [s.value for s in SourceKind] == ["search", "interrogate", "record"]
    assert [s.value for s in RecordSubjectType] == ["suspect", "location", "event"]
    assert {k.value for k in FactKind} == {
        "alibi",
        "presence",
        "witness",
        "lie",
        "trace",
        "absent_trace",
        "physical",
        "secret",
        "motive_clue",
        "clue",
    }
    assert [c.value for c in ClaimKind] == ["presence", "record_ref"]
    assert [o.value for o in Origin] == ["generated", "imported"]


def test_source_ref_shapes():
    assert search().subject is None
    SourceRef(kind=SourceKind.INTERROGATE, target="s_anna")
    SourceRef(kind=SourceKind.RECORD, target="ledger", subject="s_anna")
    with pytest.raises(ValidationError):
        SourceRef(kind=SourceKind.RECORD, target="ledger")  # a record needs a subject
    with pytest.raises(ValidationError):
        SourceRef(kind=SourceKind.SEARCH, target="l_study", subject="s_anna")  # others forbid it


def test_source_refs_are_hashable_and_equal_by_value():
    assert search() == search()
    assert len({search(), search(), search("l_garden")}) == 2


def test_claim_shapes():
    Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=2, place="l_study")
    Claim(kind=ClaimKind.RECORD_REF, actor="s_anna", slot=2, record_kind="ledger")
    with pytest.raises(ValidationError):
        Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=2)  # presence needs a place
    with pytest.raises(ValidationError):
        Claim(kind=ClaimKind.RECORD_REF, actor="s_anna", slot=2, place="l_study")
    with pytest.raises(ValidationError):
        Claim(kind=ClaimKind.PRESENCE, actor="s_anna", slot=-1, place="l_study")


def test_models_are_frozen_and_reject_unknown_fields():
    effect = Effect(axis=Axis.WHO, candidate="s_anna", kind=EffectKind.RULES_OUT)
    with pytest.raises(ValidationError):
        effect.candidate = "s_boris"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Effect(axis=Axis.WHO, candidate="s_anna", kind=EffectKind.RULES_OUT, extra=1)  # type: ignore[call-arg]


def test_fact_defaults_and_sorted_set_like_tuples():
    fact = Fact(
        id="f_a",
        kind=FactKind.CLUE,
        source=search(),
        requires=("f_z", "f_b"),
        exposed_by=("f_y", "f_c"),
        timeline_ref=("t_2", "t_1"),
        effects=(
            Effect(axis=Axis.WHY, candidate="v_x", kind=EffectKind.SUPPORTS),
            Effect(axis=Axis.HOW, candidate="m_x", kind=EffectKind.PROVES),
            Effect(axis=Axis.HOW, candidate="m_a", kind=EffectKind.RULES_OUT),
        ),
    )
    assert fact.requires == ("f_b", "f_z")
    assert fact.exposed_by == ("f_c", "f_y")
    assert fact.timeline_ref == ("t_1", "t_2")
    assert [(e.axis.value, e.candidate) for e in fact.effects] == [
        ("how", "m_a"),
        ("how", "m_x"),
        ("why", "v_x"),
    ]
    assert fact.truthful is True and fact.speaker is None and fact.claim is None
    assert fact.text == "" and fact.contradiction is None


def test_equal_facts_compare_equal_regardless_of_input_order():
    a = Fact(id="f_a", kind=FactKind.CLUE, source=search(), requires=("f_b", "f_c"))
    b = Fact(id="f_a", kind=FactKind.CLUE, source=search(), requires=("f_c", "f_b"))
    assert a == b


def test_model_copy_skips_validation_so_tests_can_build_broken_cases():
    fact = Fact(id="f_a", kind=FactKind.CLUE, source=search())
    broken = fact.model_copy(update={"requires": ("f_z", "f_a")})
    assert broken.requires == ("f_z", "f_a")  # not re-sorted: deliberately unvalidated
