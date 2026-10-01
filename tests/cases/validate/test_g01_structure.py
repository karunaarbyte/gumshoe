from gumshoe.cases.model.entities import Effect, Fact, SourceRef
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind, SourceKind
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import add_fact, replace_fact, replace_in, replace_spec


def codes_of(case):
    return validate(case, profile=Profile.CUSTOM).codes()


def test_clean_fixture_has_no_group_1_issues():
    assert validate(build_case(), profile=Profile.CUSTOM).skipped_groups == ()


def test_duplicate_ids_are_reported_once_per_id_with_the_id_as_subject():
    case = add_fact(build_case(), build_case().facts[0].model_copy())
    (issue,) = validate(case, profile=Profile.CUSTOM).of_code("DUPLICATE_ID")
    assert issue.subjects == (case.facts[0].id,)


def test_ids_must_be_unique_across_entity_kinds():
    case = replace_in(
        build_case(), "locations", "l_garden", id="s_anna"
    )  # a location reusing a suspect id
    assert "DUPLICATE_ID" in codes_of(case)


def test_dangling_references_name_the_owner_the_missing_id_and_the_field():
    case = replace_fact(build_case(), "f_key", requires=("f_missing",))
    (issue,) = validate(case, profile=Profile.CUSTOM).of_code("DANGLING_REF")
    assert issue.subjects == ("f_key", "f_missing") and dict(issue.params)["field"] == "requires"


def test_every_reference_kind_is_checked():
    base = build_case()
    alibi_claim = next(f for f in base.facts if f.id == "f_alibi_anna").claim
    assert alibi_claim is not None
    cases = [
        replace_fact(base, "f_key", exposed_by=("f_x",)),
        replace_fact(base, "f_key", timeline_ref=("t_x",)),
        replace_fact(base, "f_lie_anna", speaker="s_x"),
        replace_fact(base, "f_alibi_anna", claim=alibi_claim.model_copy(update={"actor": "s_x"})),
        replace_fact(base, "f_key", source=SourceRef(kind=SourceKind.SEARCH, target="l_x")),
        replace_fact(base, "f_key", source=SourceRef(kind=SourceKind.INTERROGATE, target="s_x")),
        replace_fact(
            base, "f_lie_anna", exposure_hook=SourceRef(kind=SourceKind.SEARCH, target="l_x")
        ),
        replace_in(base, "suspects", "s_anna", motive="v_x"),
        replace_in(base, "suspects", "s_anna", secret_fact="f_x"),
        replace_in(base, "suspects", "s_anna", knows=("f_x",)),
        replace_in(base, "locations", "l_garden", requires=("f_x",)),
        replace_in(base, "timeline", "t_crime", actor="s_x"),
        replace_in(base, "timeline", "t_crime", place="l_x"),
        base.model_copy(update={"start": base.start.model_copy(update={"locations": ("l_x",)})}),
    ]
    for case in cases:
        assert "DANGLING_REF" in codes_of(case)


def test_a_record_source_must_be_declared_and_its_subject_must_exist():
    base = build_case()
    sources = (
        base.record_sources[0].model_copy(update={"subject": "s_nobody"}),
        *base.record_sources[1:],
    )
    assert "DANGLING_REF" in codes_of(base.model_copy(update={"record_sources": sources}))


def test_an_effect_naming_a_wholly_unknown_candidate_is_dangling_not_wrong_axis():
    case = replace_fact(
        build_case(),
        "f_sup_poison",
        effects=(Effect(axis=Axis.HOW, candidate="m_x", kind=EffectKind.SUPPORTS),),
    )
    assert "DANGLING_REF" in codes_of(case) and "EFFECT_WRONG_AXIS" not in codes_of(case)


def test_the_validator_never_raises_on_a_pathologically_garbled_case():
    case = build_case().model_copy(
        update={
            "facts": tuple(
                f.model_copy(update={"requires": ("x" * 5000,), "effects": (), "speaker": "\x00"})
                for f in build_case().facts
            ),
            "start": build_case().start.model_copy(update={"facts": ("nope",)}),
        }
    )
    report = validate(case, profile=Profile.CUSTOM)
    assert not report.ok and report.skipped_groups == tuple(range(2, 12))


def test_size_caps_stop_all_further_work():
    many = [
        Fact(
            id=f"f_x{i}",
            kind=FactKind.CLUE,
            source=SourceRef(kind=SourceKind.SEARCH, target="l_study"),
        )
        for i in range(500)
    ]
    report = validate(
        build_case().model_copy(update={"facts": tuple(many)}), profile=Profile.CUSTOM
    )
    assert report.codes() == {"TOO_LARGE"} and report.skipped_groups == tuple(range(2, 12))


def test_count_mismatch_covers_record_kinds_by_distinct_kind():
    assert "COUNT_MISMATCH" in codes_of(replace_spec(build_case(), record_kinds=3))


def test_duplicate_record_sources_are_duplicate_ids():
    base = build_case()
    dup = base.model_copy(update={"record_sources": (*base.record_sources, base.record_sources[0])})
    (issue,) = validate(dup, profile=Profile.CUSTOM).of_code("DUPLICATE_ID")
    assert issue.subjects == ("gate_log/l_garden",)


def test_an_empty_record_subject_is_a_shape_error():
    case = replace_fact(
        build_case(),
        "f_sup_rope",
        source=SourceRef.model_construct(kind=SourceKind.RECORD, target="gate_log", subject=""),
    )
    assert "SOURCE_SHAPE" in codes_of(case)
