import json

import pytest

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.model.roles import FIELD_ROLES, MODEL_CLASSES, FieldRole
from gumshoe.cases.model.serialize import (
    dump_case,
    load_case,
    skeleton_dict,
    skeleton_digest,
    skin_dict,
    skin_hash,
)
from tests.cases.model.builders import tiny_case


def test_every_field_of_every_model_is_classified_exactly_once():
    for cls in MODEL_CLASSES:
        table = FIELD_ROLES[cls.__name__]
        assert set(table) == set(cls.model_fields), cls.__name__
        assert all(isinstance(role, FieldRole) for role in table.values())


def test_no_unregistered_roles_table_entries():
    assert set(FIELD_ROLES) == {cls.__name__ for cls in MODEL_CLASSES}


def test_the_pinned_classification_of_the_important_fields():
    case_roles = FIELD_ROLES["Case"]
    for name in (
        "id",
        "seed",
        "origin",
        "pack_ref",
        "generator_version",
        "pack_versions",
        "attempt",
        "stage_attempts",
        "skin_rev",
        "skin_hash",
        "theme",
    ):
        assert case_roles[name] is FieldRole.META, name
    for name in ("intro", "smalltalk_allow"):
        assert case_roles[name] is FieldRole.SKIN, name
    for name in (
        "schema_version",
        "skeleton_algo_version",
        "spec",
        "scene_type",
        "truth",
        "start",
        "suspects",
        "locations",
        "record_sources",
        "methods",
        "motives",
        "timeline",
        "facts",
    ):
        assert case_roles[name] is FieldRole.SKELETON, name
    assert (
        FIELD_ROLES["Fact"]["text"] is FieldRole.SKIN
        and FIELD_ROLES["Fact"]["contradiction"] is FieldRole.SKIN
    )
    assert FIELD_ROLES["Fact"]["truthful"] is FieldRole.SKELETON
    assert FIELD_ROLES["Suspect"]["label"] is FieldRole.SKELETON
    for name in ("display_name", "description", "traits", "style", "secret_text"):
        assert FIELD_ROLES["Suspect"][name] is FieldRole.SKIN, name
    assert FIELD_ROLES["Location"]["name"] is FieldRole.SKIN


def test_dump_load_round_trip_is_exact_and_byte_stable():
    case = tiny_case()
    data = dump_case(case)
    assert load_case(data) == case
    assert dump_case(load_case(data)) == data
    assert json.loads(data)["suspects"][0]["id"] == "s_a"


def test_skeleton_dict_has_no_skin_and_no_meta():
    d = skeleton_dict(tiny_case())
    assert "intro" not in d and "id" not in d and "seed" not in d and "skin_hash" not in d
    assert "smalltalk_allow" not in d
    assert all("display_name" not in s and "description" not in s for s in d["suspects"])
    assert all("text" not in f for f in d["facts"])
    assert d["schema_version"] == 1 and d["truth"] == {"who": "s_a", "how": "m_x", "why": "v_a"}
    assert d["suspects"][0]["label"] == "Abe the maid"


def test_digest_is_the_domain_separated_hash_of_the_canonical_skeleton():
    case = tiny_case()
    expected = domain_digest("gumshoe.case.skeleton.v1", canonical_json(skeleton_dict(case)))
    assert skeleton_digest(case) == expected
    assert len(expected) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"intro": "A different intro."},
        {"smalltalk_allow": ("candle",)},
        {"id": "c_other"},
        {"seed": 7},
        {"attempt": 3},
        {"skin_rev": 5},
        {"theme": "castle"},
        {"generator_version": "g2"},
    ],
)
def test_skin_and_meta_edits_do_not_change_the_digest(change):
    base = tiny_case()
    assert skeleton_digest(base.model_copy(update=change)) == skeleton_digest(base)


def test_skin_edits_inside_entities_do_not_change_the_digest():
    base = tiny_case()
    renamed = base.model_copy(
        update={
            "suspects": tuple(
                s.model_copy(update={"display_name": "X", "traits": ("odd",)})
                for s in base.suspects
            ),
            "facts": tuple(f.model_copy(update={"text": "changed"}) for f in base.facts),
        }
    )
    assert skeleton_digest(renamed) == skeleton_digest(base)
    assert skin_hash(renamed) != skin_hash(base)


@pytest.mark.parametrize("field", ["scene_type", "schema_version", "skeleton_algo_version"])
def test_skeleton_edits_change_the_digest(field):
    base = tiny_case()
    new = base.model_copy(update={field: 99 if isinstance(getattr(base, field), int) else "other"})
    assert skeleton_digest(new) != skeleton_digest(base)


def test_label_and_truth_and_fact_logic_edits_change_the_digest():
    base = tiny_case()
    d0 = skeleton_digest(base)
    relabel = base.model_copy(
        update={
            "suspects": (
                base.suspects[0].model_copy(update={"label": "Abe the cook"}),
                base.suspects[1],
            )
        }
    )
    assert skeleton_digest(relabel) != d0
    retruth = base.model_copy(update={"truth": base.truth.model_copy(update={"who": "s_b"})})
    assert skeleton_digest(retruth) != d0
    lie = base.model_copy(
        update={"facts": (base.facts[0].model_copy(update={"truthful": False}), base.facts[1])}
    )
    assert skeleton_digest(lie) != d0


def test_skin_hash_covers_skin_and_smalltalk_but_not_the_skeleton():
    base = tiny_case()
    h0 = skin_hash(base)
    assert skin_hash(base.model_copy(update={"intro": "new"})) != h0
    assert skin_hash(base.model_copy(update={"smalltalk_allow": ("x",)})) != h0
    assert skin_hash(base.model_copy(update={"scene_type": "other"})) == h0
    assert "intro" in skin_dict(base)


def test_digest_is_independent_of_input_order():
    case = tiny_case()
    shuffled = load_case(
        canonical_json(
            {
                **case.model_dump(mode="json"),
                "facts": list(reversed(case.model_dump(mode="json")["facts"])),
            }
        )
    )
    assert skeleton_digest(shuffled) == skeleton_digest(case)


def test_editing_fact_text_changes_the_skin_hash_but_requires_does_not():
    base = tiny_case()

    def with_fact(**update):
        facts = (base.facts[0].model_copy(update=update), base.facts[1])
        return base.model_copy(update={"facts": facts})

    assert skin_hash(with_fact(text="other words")) != skin_hash(base)
    assert skin_hash(with_fact(requires=("f_two",))) == skin_hash(base)
    assert skin_dict(base)["facts"][0]["id"] == "f_one"


def test_skin_hash_ignores_the_case_id_which_is_meta():
    base = tiny_case()
    other = base.model_copy(update={"id": "c_other"})
    assert skin_hash(other) == skin_hash(base)
    assert "id" not in skin_dict(base)
