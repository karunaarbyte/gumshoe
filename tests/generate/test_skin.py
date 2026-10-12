import json

import pytest

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.pipeline import identity_skin, no_lint, run_pipeline
from gumshoe.cases.generate.skin import _Deal, template_skin
from gumshoe.cases.model.enums import FactKind
from gumshoe.cases.model.serialize import skeleton_digest
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.generate.helpers import PRESET_NAMES, castle, castle_with
from tests.generate.skin_helpers import made, renderings, skinned

CASES = [(seed, preset) for preset in PRESET_NAMES for seed in range(8)]


@pytest.mark.parametrize(("seed", "preset"), CASES)
def test_every_text_field_is_filled_and_only_lies_have_a_contradiction(seed, preset):
    pack, case = castle(), made(seed, preset)
    assert case.intro and case.smalltalk_allow == pack.smalltalk_allow
    for fact in case.facts:
        assert fact.text.strip()
        assert bool(fact.contradiction) == (fact.kind is FactKind.LIE)
    for suspect in case.suspects:
        assert suspect.display_name == suspect.label
        assert suspect.traits and suspect.style
        secret = next(f for f in case.facts if f.id == suspect.secret_fact)
        assert suspect.secret_text == secret.text
    assert all(x.name and x.description for x in case.locations)
    assert len({x.name for x in case.locations}) == len(case.locations)


@pytest.mark.parametrize(("seed", "preset"), CASES)
def test_every_fact_renders_from_its_own_family_or_list(seed, preset):
    pack, case = castle(), made(seed, preset)
    for fact in case.facts:
        assert fact.text in renderings(case, pack, fact), (fact.kind, fact.text)


@pytest.mark.parametrize(("seed", "preset"), CASES)
def test_the_skin_leaves_the_skeleton_alone(seed, preset):
    pack = castle()
    _, plain = bare(pack, seed, preset)
    skinned = made(seed, preset)
    assert skeleton_digest(skinned) == skeleton_digest(plain)
    assert skinned.id == plain.id
    assert issue_codes(skinned, pack) == issue_codes(plain, pack)
    assert not [
        i for i in validate(skinned, pack, Profile.STRICT).issues if i.severity.value == "error"
    ]


def test_the_intro_names_the_victim_the_scene_and_the_crime_slot():
    pack, case = castle(), made(2, "standard")
    event = next(e for e in case.timeline if e.action == "crime")
    scene = next(x for x in case.locations if x.id == event.place)
    during = pack.slot_defs[event.slot].during
    assert any(case.intro.startswith(v.text) or v.text in case.intro for v in pack.victims)
    assert scene.name in case.intro and during in case.intro


def test_the_dealer_does_not_repeat_a_variant_until_the_list_is_used_up():
    from gumshoe.cases.generate.streams import Stream

    deal = _Deal(Stream.root(1, "spec", 1, 0, "skin"))
    variants = ["a", "b", "c"]
    first = [deal.next("k", variants) for _ in range(3)]
    assert sorted(first) == variants
    assert deal.next("k", variants) == first[0]  # then it wraps
    assert deal.next("other", variants) in variants  # lists are dealt apart
    with pytest.raises(GenerationError, match="no text for empty"):
        deal.next("empty", [])


def issue_codes(case, pack):
    return sorted(i.code for i in validate(case, pack, Profile.STRICT).issues)


def bare(pack, seed=1, preset="standard"):
    """The assembled case with no wording, and the context and stream the skin would get."""
    ctx = GenContext.of(pack, seed, preset)
    case, _ = run_pipeline(ctx, skin=identity_skin, lint=no_lint)
    return ctx, case


def test_a_pack_without_the_text_for_a_fact_raises_a_generation_error():
    def drop_hints(data):
        for motive in data["motive_defs"]:
            motive["hints"] = []

    ctx, case = bare(castle_with(drop_hints))
    with pytest.raises(GenerationError, match="no text for hints/"):
        template_skin(ctx, ctx.stream("skin"), case)


def test_a_case_the_pack_does_not_know_raises_a_generation_error_not_a_lookup_error():
    ctx, case = bare(castle())
    stranger = case.locations[0].model_copy(update={"kind": "nowhere"})
    odd_place = case.model_copy(update={"locations": (stranger, *case.locations[1:])})
    with pytest.raises(GenerationError, match="location kind 'nowhere'"):
        template_skin(ctx, ctx.stream("skin"), odd_place)
    unknown = tuple(m.model_copy(update={"type": "nothing"}) for m in case.methods)
    odd_method = case.model_copy(update={"methods": unknown})
    with pytest.raises(GenerationError, match="method 'nothing'"):
        template_skin(ctx, ctx.stream("skin"), odd_method)
    odd_role = case.model_copy(
        update={"suspects": tuple(s.model_copy(update={"role": "nobody"}) for s in case.suspects)}
    )
    with pytest.raises(GenerationError, match="role 'nobody'|no name entry"):
        template_skin(ctx, ctx.stream("skin"), odd_role)


def test_a_key_that_no_suspect_needs_cannot_be_rendered():
    ctx, case = bare(castle(), preset="long")  # long is always gated at depth 2: it has keys
    loose = case.model_copy(
        update={"suspects": tuple(s.model_copy(update={"requires": ()}) for s in case.suspects)}
    )
    with pytest.raises(GenerationError, match="needs the suspect"):
        template_skin(ctx, ctx.stream("skin"), loose)


def test_a_wording_edit_changes_the_text_but_not_the_id_or_the_skeleton():
    def reword(data):
        for family in data["families"]:
            if family["kind"] == "intro":
                family["variants"] = [v[:-1] + ", it was said." for v in family["variants"]]

    a, b = skinned(castle(), 4, "standard"), skinned(castle_with(reword), 4, "standard")
    assert a.id == b.id and skeleton_digest(a) == skeleton_digest(b)
    assert a.skin_hash != b.skin_hash and a.intro != b.intro


def test_a_new_skin_stream_gives_other_wording_for_the_same_skeleton():
    ctx, case = bare(castle(), seed=5)
    one = template_skin(ctx, ctx.stream("skin", 0), case)
    two = template_skin(ctx, ctx.stream("skin", 1), case)
    assert skeleton_digest(one) == skeleton_digest(two)
    assert [f.text for f in one.facts] != [f.text for f in two.facts]


def test_the_case_text_is_json_stable():
    case = made(1, "short")
    assert json.loads(case.model_dump_json())["intro"] == case.intro
