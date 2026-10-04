import pytest
from pydantic import ValidationError

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Event,
    Limits,
    Location,
    PackRef,
    RecordSource,
    Spec,
    Start,
    Suspect,
    Truth,
)
from gumshoe.cases.model.enums import Origin, RecordSubjectType
from tests.cases.model.builders import tiny_case, tiny_limits


def test_entity_lists_are_sorted_by_id_regardless_of_input_order():
    case = tiny_case()
    assert [s.id for s in case.suspects] == ["s_a", "s_b"]
    assert [m.id for m in case.motives] == ["v_a", "v_b"]
    assert [f.id for f in case.facts] == ["f_one", "f_two"]
    assert case.start.suspects == ("s_a", "s_b")


def test_shuffled_construction_equals_sorted_construction():
    a = tiny_case()
    b = a.model_validate(
        {
            **a.model_dump(),
            "suspects": list(reversed(a.model_dump()["suspects"])),
            "facts": list(reversed(a.model_dump()["facts"])),
        }
    )
    assert a == b


def test_defaults():
    case = tiny_case()
    assert case.origin is Origin.GENERATED
    assert case.pack_ref is None and case.seed is None and case.generator_version is None
    assert case.schema_version == 1 and case.skeleton_algo_version == 1
    assert case.attempt == 0 and case.stage_attempts == () and case.pack_versions == ()
    assert case.skin_rev == 0 and case.skin_hash == "" and case.smalltalk_allow == ()


def test_record_sources_sort_by_kind_then_subject():

    def rs(kind: str, subject: str) -> RecordSource:
        return RecordSource(kind=kind, subject_type=RecordSubjectType.SUSPECT, subject=subject)

    base = tiny_case()
    case = Case(
        **{
            **base.model_dump(),
            "record_sources": [rs("ledger", "s_b"), rs("gate_log", "s_z"), rs("ledger", "s_a")],
        }
    )
    assert [(r.kind, r.subject) for r in case.record_sources] == [
        ("gate_log", "s_z"),
        ("ledger", "s_a"),
        ("ledger", "s_b"),
    ]


def test_set_like_entity_fields_are_sorted():
    s = Suspect(
        id="s_a",
        label="A",
        role="r",
        motive="v",
        secret_fact="f",
        aliases=("zed", "abe"),
        requires=("f_z", "f_a"),
        knows=("f_y", "f_b"),
    )
    assert (
        s.aliases == ("abe", "zed") and s.requires == ("f_a", "f_z") and s.knows == ("f_b", "f_y")
    )
    loc = Location(id="l_a", kind="k", aliases=("b", "a"), requires=("f_2", "f_1"))
    assert loc.aliases == ("a", "b") and loc.requires == ("f_1", "f_2") and loc.decorative is False


def test_models_are_frozen_hashable_and_forbid_extra_fields():
    case = tiny_case()
    with pytest.raises(ValidationError):
        case.id = "other"  # type: ignore[misc]
    assert isinstance(hash(case), int)
    with pytest.raises(ValidationError):
        Truth(who="a", how="b", why="c", extra="x")  # type: ignore[call-arg]


def test_spec_requires_all_sizes_and_limits():
    with pytest.raises(ValidationError):
        Spec(preset="x", suspects=1)  # type: ignore[call-arg]
    spec = Spec(
        preset="custom",
        suspects=3,
        methods=3,
        motives=3,
        locations=3,
        record_kinds=2,
        slots=4,
        opportunity=1,
        limits=tiny_limits(),
    )
    assert spec.source_cap == 4 and spec.fairness_tolerance == 1


def test_limits_are_integers_only():
    with pytest.raises(ValidationError):
        Limits(
            solution_min=1.5,
            solution_max=9,
            depth_min=0,
            depth_max=3,
            actions_min=1,
            actions_max=9,
            decisive_pct_max=50,
        )


def test_pack_ref_and_start_sorting():
    ref = PackRef(id="castle", skeleton_hash="ab" * 32)
    assert ref.id == "castle"
    assert Start(locations=("l_b", "l_a"), suspects=(), facts=("f_2", "f_1")).facts == (
        "f_1",
        "f_2",
    )


def test_event_slot_must_not_be_negative():
    with pytest.raises(ValidationError):
        Event(id="t_1", slot=-1, actor="s_a", place="l_x", action="crime")


def test_record_sources_with_equal_kind_and_subject_sort_by_subject_type_then_requires():
    def rs(subject_type: RecordSubjectType, requires: tuple[str, ...] = ()) -> RecordSource:
        return RecordSource(
            kind="ledger", subject_type=subject_type, subject="x_1", requires=requires
        )

    items = [
        rs(RecordSubjectType.SUSPECT),
        rs(RecordSubjectType.LOCATION, ("f_b",)),
        rs(RecordSubjectType.LOCATION),
    ]
    base = tiny_case().model_dump()
    forward = Case(**{**base, "record_sources": items})
    backward = Case(**{**base, "record_sources": list(reversed(items))})
    assert forward == backward
