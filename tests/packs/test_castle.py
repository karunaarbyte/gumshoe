import re
import tomllib
from collections.abc import Iterable
from importlib.resources import files

import pytest

from gumshoe.cases.core.labels import token_set
from gumshoe.cases.model.pack import FamilyDef, MethodDef, MotiveDef, Pack
from gumshoe.cases.model.spec import PRESETS, derive_spec
from gumshoe.cases.packs import LoadResult, load_pack
from gumshoe.cases.packs.check.capacity import eligible_roles, hosting_scenes
from gumshoe.cases.packs.check.lint import SAMPLES, render
from gumshoe.cases.tools.builtin import load_builtin_pack

PRESENCE_IDS = (
    "alibi",
    "lie_alibi",
    "witness_sighting",
    "witness_hearing",
    "presence_record",
    "lie_record",
    "lie_accusation",
)
TIME_WORDS = (
    "evening",
    "night",
    "noon",
    "morning",
    "afternoon",
    "dawn",
    "dusk",
    "supper",
    "all day",
    "that day",
)
CERTAINTY_WORDS = (
    "reliable",
    "every account",
    "plain view",
    "left it at that",
    "too readily",
    "thin",
    "unravel",
    "hollow",
    "rehearsed",
    "odd",
    "rather",
    "suspicious",
    "undisturbed",
    "exactly",
    "yawn",
    "tired",
    "flustered",
)
WITNESS_NOUNS = (
    "pilgrim",
    "porter",
    "page",
    "guest",
    "watchman",
    "laundress",
    "pedlar",
    "mason",
    "scullion",
    "messenger",
    "merchant",
    "man-at-arms",
)
HARD_CODED_RECORD_NAMES = (
    "household books",
    "day book",
    "watch book",
    "register",
    "tally",
    "ledger",
    "gate log",
)
AUDIENCES = (
    "the household",
    "a visitor",
    "a guest",
    "the guards",
    "the visitors",
    "the servants",
)
# A "self-report" variant is one that starts with the subject's own name and has a speech verb.
SPEECH_VERBS = ("said", "stated", "told", "remembered", "mentioned", "recalled", "pointed out")
NEGATIONS = ("no", "not", "nothing", "never", "without", "nor", "none", "little")
BODY_WORDS = (
    "skull",
    "lips",
    "throat",
    "neck",
    "limb",
    "body",
    "corpse",
    "victim",
    "blood",
    "bone",
    "wound",
    "stain",
)
ALLOWED_SECRET_SLOTS = {"who", "^who", "who.subj", "who.poss", "^who.poss"}
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
SAMPLE = {
    "who": "Berta",
    "who.subj": "she",
    "who.poss": "her",
    "place": "the Great Hall",
    "place.in": "in the Great Hall",
    "time.phrase": "at vespers",
    "time.at": "at vespers",
    "time.during": "during vespers",
    "record": "the household register",
    "victim": "Lord Aldric",
    "victim.subj": "he",
    "victim.poss": "his",
}


def _castle_bytes() -> bytes:
    return files("gumshoe.cases.packs").joinpath("castle.toml").read_bytes()


def _castle() -> LoadResult:
    return load_pack(_castle_bytes())


@pytest.fixture
def pack() -> Pack:
    loaded = _castle().pack
    assert loaded is not None
    return loaded


def _family(pack: Pack, family_id: str) -> FamilyDef:
    return next(f for f in pack.families if f.id == family_id)


def _words(text: str, words: Iterable[str]) -> set[str]:
    """The given words and phrases found in text as whole words, case-insensitive."""
    return {
        w for w in words if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text, re.IGNORECASE)
    }


def _all_texts(pack: Pack) -> list[str]:
    """Every family variant and every record presence line."""
    return [v for f in pack.families for v in f.variants] + [
        line for r in pack.record_defs for line in r.presence
    ]


def _slots(text: str) -> set[str]:
    """The placeholder names in a template, with the capitalising ^ marker stripped."""
    return {name.lstrip("^") for name in PLACEHOLDER.findall(text)}


def _found(texts: Iterable[str], words: Iterable[str]) -> list[tuple[str, set[str]]]:
    return [(t, hit) for t in texts if (hit := _words(t, words))]


def _union(texts: Iterable[str], words: Iterable[str]) -> set[str]:
    return {w for t in texts for w in _words(t, words)}


def _self_reports(variants: Iterable[str]) -> int:
    return sum(1 for v in variants if v.startswith("{^who} ") and _words(v, SPEECH_VERBS))


def _mean_length(variants: Iterable[str]) -> float:
    lengths = [len(render(v, SAMPLES[0])) for v in variants]
    return sum(lengths) / len(lengths)


def _edit_first_variant(pack: Pack, family_id: str) -> Pack:
    families = tuple(
        f.model_copy(update={"variants": ("An edited sentence.", *f.variants[1:])})
        if f.id == family_id
        else f
        for f in pack.families
    )
    return pack.model_copy(update={"families": families})


def test_the_castle_loads_with_no_issues_under_the_real_presets():
    result = _castle()
    assert [(i.code, i.path) for i in result.issues] == [] and result.pack is not None


def test_the_castle_resource_is_found_by_the_builtin_loader():
    assert load_builtin_pack("castle").id == "castle"


def test_the_castle_meets_the_spec_counts(pack):
    assert len(pack.roles) >= 8 and len(pack.motive_defs) >= 8
    assert len(pack.location_defs) >= 7 and len(pack.method_defs) >= 6
    assert len(pack.record_defs) >= 3 and len(pack.families) >= 12


def test_the_castle_skeleton_hash_ignores_a_wording_edit(pack):
    assert _edit_first_variant(pack, "alibi").skeleton_hash() == pack.skeleton_hash()


def test_the_castle_skeleton_hash_ignores_a_skin_rev_bump(pack):
    assert pack.model_copy(update={"skin_rev": 9}).skeleton_hash() == pack.skeleton_hash()


def test_the_castle_skeleton_hash_changes_with_a_new_role_name(pack):
    role = pack.roles[0]
    extra = role.names[0].model_copy(update={"text": "Zed"})
    roles = (role.model_copy(update={"names": (*role.names, extra)}), *pack.roles[1:])
    assert pack.model_copy(update={"roles": roles}).skeleton_hash() != pack.skeleton_hash()


def test_the_castle_skeleton_hash_changes_when_a_trace_kind_is_removed(pack):
    method = pack.method_defs[0].model_copy(update={"traces": ()})
    methods = (method, *pack.method_defs[1:])
    assert pack.model_copy(update={"method_defs": methods}).skeleton_hash() != pack.skeleton_hash()


def test_the_castle_claims_exactly_three_presets_and_fits_its_capacity_in_its_pools(pack):
    assert set(pack.presets) == {"short", "standard", "long"}
    cap = pack.capacity
    assert cap.max_locations <= len(pack.location_defs)
    assert cap.max_methods <= len(pack.method_defs)
    assert cap.max_record_kinds <= len(pack.record_defs)
    assert cap.max_suspects <= len(pack.roles) and cap.max_suspects <= len(pack.motive_defs)


def test_every_claimed_preset_has_at_least_three_hosting_scenes(pack):
    expected_minimum = {"short": 7, "standard": 7, "long": 4}  # measured: 7, 7, 4
    for name in pack.presets:
        spec = derive_spec(name, pack, PRESETS)
        hosts = hosting_scenes(pack, spec)
        assert len(hosts) >= 3, name
        assert len(hosts) >= expected_minimum[name], name  # long was once one scene


def test_each_scene_has_exactly_one_location_kind(pack):
    for scene in pack.scene_types:
        assert len(scene.location_kinds) == 1, scene.key


def test_every_method_is_placeable_in_every_scene_it_is_allowed_in(pack):
    traces = {m.key: m.traces for m in pack.method_defs}
    for scene in pack.scene_types:
        kinds = {t.kind for key in scene.allowed_methods for t in traces[key]}
        assert set(scene.allowed_trace_kinds) == kinds, scene.key
        for key in scene.allowed_methods:
            for trace in traces[key]:
                assert set(scene.location_kinds) <= set(trace.location_kinds), (scene.key, key)


def test_every_method_is_allowed_in_at_least_four_scenes(pack):
    for method in pack.method_defs:
        scenes = [s.key for s in pack.scene_types if method.key in s.allowed_methods]
        assert len(scenes) >= 4, method.key


def test_presence_families_carry_the_full_claim_and_no_hard_coded_time(pack):
    for family_id in PRESENCE_IDS:
        family = _family(pack, family_id)
        assert set(family.claim_slots) == {"who", "place.in", "time.at"}, family_id
        assert _found(family.variants, TIME_WORDS) == [], family_id
        for variant in family.variants:
            assert {"who", "place.in", "time.at"} <= _slots(variant), variant


def test_record_presence_lines_carry_who_place_and_time(pack):
    for record in pack.record_defs:
        for line in record.presence:
            assert {"who", "place.in", "time.at"} <= _slots(line), line


def test_no_suspect_role_appears_as_a_witness_in_any_family(pack):
    roles = [r.key for r in pack.roles]
    variants = [v for f in pack.families for v in f.variants]
    assert _found(variants, roles) == []


def test_no_certainty_or_evasion_words_in_any_variant_or_record_line(pack):
    assert _found(_all_texts(pack), CERTAINTY_WORDS) == []


def test_the_whole_word_match_does_not_flag_a_longer_word():
    assert _words("Everything looked thin.", ["thin"]) == {"thin"}
    assert _words("Everything looked tidy.", ["thin"]) == set()


@pytest.mark.parametrize("truth, lie", [("alibi", "lie_alibi"), ("presence_record", "lie_record")])
def test_truth_and_lie_families_use_the_same_nouns_records_audiences_and_shape(pack, truth, lie):
    a, b = _family(pack, truth).variants, _family(pack, lie).variants
    assert _union(a, WITNESS_NOUNS) == _union(b, WITNESS_NOUNS)
    assert _union(a, AUDIENCES) == _union(b, AUDIENCES)
    assert _self_reports(a) == _self_reports(b)
    assert abs(_mean_length(a) - _mean_length(b)) <= 0.15 * max(_mean_length(a), _mean_length(b))


def test_rule_out_and_proof_share_one_shape_and_say_nothing_negative(pack):
    proof, ruled_out = _family(pack, "trace_inspection"), _family(pack, "absent_trace")
    assert len(proof.variants) == len(ruled_out.variants)
    assert _found(proof.variants + ruled_out.variants, NEGATIONS) == []


def test_method_traces_describe_objects_not_bodies(pack):
    for method in pack.method_defs:
        assert len(method.traces) == 1, method.key
        assert len(method.traces[0].templates) == 2, method.key
        assert _found(method.traces[0].templates, BODY_WORDS) == [], method.key


def test_secrets_carry_no_place_or_time(pack):
    for motive in pack.motive_defs:
        for secret in motive.secrets:
            assert set(PLACEHOLDER.findall(secret)) <= ALLOWED_SECRET_SLOTS, secret


def test_every_role_has_a_suspect_record_kind(pack):
    subject = {d.key: d.subject for d in pack.record_defs}
    for role in pack.roles:
        assert any(subject[k] == "suspect" for k in role.record_kinds), role.key


def test_every_motive_is_allowed_by_at_least_three_roles(pack):
    for motive in pack.motive_defs:
        allowed = [r.key for r in pack.roles if motive.key in r.motive_types]
        assert len(allowed) >= 3, motive.key


def test_role_names_are_distinct_across_the_pack(pack):
    names = [e.text for r in pack.roles for e in r.names]
    assert len(names) == 16 and len(set(names)) == len(names)


def test_the_castle_toml_text_matches_the_loaded_pack_for_its_role_keys(pack):
    raw = tomllib.loads(_castle_bytes().decode())
    assert set(raw["roles"]) == {r.key for r in pack.roles}


def test_no_two_family_variants_render_to_the_same_sentence(pack):
    rendered = [render(v, SAMPLE) for f in pack.families for v in f.variants]
    duplicates = sorted({s for s in rendered if rendered.count(s) > 1})
    assert duplicates == []


def _candidate_tokens(pack: Pack) -> frozenset[str]:
    """Every token of every method and motive label and alias
    (the validator's collision set)."""
    found: set[str] = set()
    defs: tuple[MethodDef | MotiveDef, ...] = (*pack.method_defs, *pack.motive_defs)
    for d in defs:
        found |= token_set(d.label, *d.aliases)
    return frozenset(found)


def test_every_role_has_a_distinct_noun_that_collides_with_no_candidate_token(
    pack,
):
    nouns = [r.noun for r in pack.roles]
    assert all(n.strip() for n in nouns)
    assert len(set(nouns)) == len(nouns)
    per_role = [token_set(n) for n in nouns]
    assert sum(len(t) for t in per_role) == len(frozenset().union(*per_role))  # no shared token
    assert not frozenset().union(*per_role) & _candidate_tokens(pack)


def test_no_role_name_collides_with_a_candidate_token(pack):
    names = {e.text for r in pack.roles for e in r.names}
    assert not token_set(*names) & _candidate_tokens(pack)


def test_no_record_display_name_collides_with_a_candidate_token(pack):
    names = {e.text for d in pack.record_defs for e in d.names}
    assert not token_set(*names) & _candidate_tokens(pack)


def test_every_record_kind_has_a_display_name_and_existing_location_kinds(pack):
    kinds = {d.key for d in pack.location_defs}
    for record in pack.record_defs:
        assert record.names and all(e.text.strip() for e in record.names), record.key
        assert record.location_kinds and set(record.location_kinds) <= kinds, record.key


def test_the_household_register_attests_every_room_and_the_gate_log_only_the_gatehouse(pack):
    records = {d.key: d for d in pack.record_defs}
    assert set(records["chapel_register"].location_kinds) == {d.key for d in pack.location_defs}
    assert records["chapel_register"].names[0].text == "household register"
    assert records["gate_log"].location_kinds == ("gatehouse",)


def test_every_scene_leaves_at_least_seven_eligible_roles(pack):
    for scene in pack.scene_types:
        assert len(eligible_roles(pack, scene)) >= 7, scene.key


def test_no_hard_coded_record_name_is_left_in_the_families_or_the_presence_lines(pack):
    assert _found(_all_texts(pack), HARD_CODED_RECORD_NAMES) == []


def test_the_two_record_families_use_the_record_placeholder_in_the_same_variants(pack):
    truth = _family(pack, "presence_record").variants
    lie = _family(pack, "lie_record").variants
    shapes = lambda vs: [("record" in _slots(v)) for v in vs]  # noqa: E731
    assert shapes(truth) == shapes(lie)
    assert sum(shapes(truth)) >= 5


def test_every_presence_line_uses_the_record_placeholder(pack):
    for record in pack.record_defs:
        for line in record.presence:
            assert "record" in _slots(line), line
