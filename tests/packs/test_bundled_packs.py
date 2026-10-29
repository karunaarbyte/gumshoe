"""The setting-neutral rules every bundled pack must meet.

Each test here reads only the loaded `Pack` and applies a rule that holds for any setting; the
word lists are the house rules for wording. What belongs to the castle alone (its exact counts,
its pinned names) stays in `test_castle.py`.
"""

import re
from collections.abc import Iterable, Iterator
from importlib.resources import files

import pytest

from gumshoe.cases.core.labels import token_set
from gumshoe.cases.model.pack import FamilyDef, MethodDef, MotiveDef, Pack
from gumshoe.cases.model.spec import PRESETS, derive_spec
from gumshoe.cases.packs import load_pack
from gumshoe.cases.packs.check.capacity import eligible_roles, hosting_scenes
from gumshoe.cases.packs.check.lint import (
    KNOWN_PLACEHOLDERS,
    SAMPLES,
    blank_placeholders,
    placeholders,
    render,
)
from gumshoe.cases.tools.registry import bundled_pack, bundled_packs


@pytest.fixture(params=[pytest.param(info.id, id=info.id) for info in bundled_packs()])
def pack(request: pytest.FixtureRequest) -> Pack:
    found = bundled_pack(request.param)
    assert found is not None
    return found


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

CASTLE_WITNESS_NOUNS = (
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

CASTLE_HARD_CODED_RECORD_NAMES = (
    "household books",
    "day book",
    "watch book",
    "register",
    "tally",
    "ledger",
    "gate log",
)

CASTLE_AUDIENCES = (
    "the household",
    "a visitor",
    "a guest",
    "the guards",
    "the visitors",
    "the servants",
)

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


def _candidate_tokens(pack: Pack) -> frozenset[str]:
    """Every token of every method and motive label and alias
    (the validator's collision set)."""
    found: set[str] = set()
    defs: tuple[MethodDef | MotiveDef, ...] = (*pack.method_defs, *pack.motive_defs)
    for d in defs:
        found |= token_set(d.label, *d.aliases)
    return frozenset(found)


NEW_FAMILIES = {
    "physical_proof": {"who", "record"},
    "physical_clear": {"who", "record"},
    "key": {"who"},
    "contradiction": {"who", "place.in", "time.at", "record"},
    "intro": {"victim", "place.in", "time.during"},
}

CASTLE_PHYSICAL_NOUNS = ("cloak", "boots", "gloves", "sleeve", "belt", "apron", "cap", "hat")

LINER_WITNESS_NOUNS = (
    "deckhand",
    "bellboy",
    "waiter",
    "quartermaster",
    "lookout",
    "nursemaid",
    "passenger",
    "dinner guest",
    "cabin boy",
    "bosun",
    "carpenter",
    "officer",
)

LINER_AUDIENCES = ("the crew", "the passengers", "a fellow passenger", "the officers")

LINER_PHYSICAL_NOUNS = ("coat", "shoes", "gloves", "sleeve", "cuffs", "apron", "cap", "hat")

LINER_HARD_CODED_RECORD_NAMES = (
    "manifest",
    "passenger list",
    "logbook",
    "log",
    "ledger",
    "register",
    "roster",
    "day book",
)


# Hand lists for the parity and leak rules, per pack id. A pack with no entry gets an empty list,
# and the non-vacuity guard below then fails it loudly: a new setting must list its own words.
WORDS_BY_PACK: dict[str, dict[str, tuple[str, ...]]] = {
    "castle": {
        "witness": CASTLE_WITNESS_NOUNS,
        "audience": CASTLE_AUDIENCES,
        "physical": CASTLE_PHYSICAL_NOUNS,
        "record": CASTLE_HARD_CODED_RECORD_NAMES,
    },
    "liner": {
        "witness": LINER_WITNESS_NOUNS,
        "audience": LINER_AUDIENCES,
        "physical": LINER_PHYSICAL_NOUNS,
        "record": LINER_HARD_CODED_RECORD_NAMES,
    },
}
MIN_HITS = 2  # each parity list must appear in at least this many words of the pack's own texts


def _words_for(pack: Pack, kind: str) -> tuple[str, ...]:
    return WORDS_BY_PACK.get(pack.id, {}).get(kind, ())


def _record_names(pack: Pack) -> tuple[str, ...]:
    """The hand list plus every record display name and its last word, derived from the pack."""
    names = [e.text.lower() for d in pack.record_defs for e in d.names]
    return (*_words_for(pack, "record"), *names, *(n.split()[-1] for n in names))


def _family_of_kind(pack: Pack, kind: str) -> FamilyDef:
    (found,) = [f for f in pack.families if f.kind == kind]
    return found


"""The castle's wording for the evidence (2c.1b): the house rules for every new text."""


def _owned(pack: Pack) -> Iterator[tuple[str, str]]:
    """Every owned text with its key path: absent, clues, hints and the location-record entries."""
    for method in pack.method_defs:
        for trace in method.traces:
            for i, text in enumerate(trace.absent):
                yield f"method_defs.{method.key}.traces[{trace.kind}].absent[{i}]", text
        for i, text in enumerate(method.clues):
            yield f"method_defs.{method.key}.clues[{i}]", text
    for motive in pack.motive_defs:
        for i, text in enumerate(motive.hints):
            yield f"motive_defs.{motive.key}.hints[{i}]", text
    for record in pack.record_defs:
        for i, text in enumerate(record.entries):
            yield f"record_defs.{record.key}.entries[{i}]", text


def _new_texts(pack: Pack) -> list[str]:
    families = [t for kind in NEW_FAMILIES for t in _family_of_kind(pack, kind).variants]
    return [*families, *(text for _, text in _owned(pack))]


def test_the_skeleton_hash_ignores_a_wording_edit(pack):
    assert _edit_first_variant(pack, "alibi").skeleton_hash() == pack.skeleton_hash()


def test_the_skeleton_hash_ignores_a_skin_rev_bump(pack):
    assert pack.model_copy(update={"skin_rev": 9}).skeleton_hash() == pack.skeleton_hash()


def test_the_skeleton_hash_changes_with_a_new_role_name(pack):
    role = pack.roles[0]
    extra = role.names[0].model_copy(update={"text": "Zed"})
    roles = (role.model_copy(update={"names": (*role.names, extra)}), *pack.roles[1:])
    assert pack.model_copy(update={"roles": roles}).skeleton_hash() != pack.skeleton_hash()


def test_the_skeleton_hash_changes_when_a_trace_kind_is_removed(pack):
    method = pack.method_defs[0].model_copy(update={"traces": ()})
    methods = (method, *pack.method_defs[1:])
    assert pack.model_copy(update={"method_defs": methods}).skeleton_hash() != pack.skeleton_hash()


def test_every_claimed_preset_has_at_least_three_hosting_scenes(pack):
    for name in pack.presets:
        spec = derive_spec(name, pack, PRESETS)
        assert len(hosting_scenes(pack, spec)) >= 3, name


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
    assert _union(a, _words_for(pack, "witness")) == _union(b, _words_for(pack, "witness"))
    assert _union(a, _words_for(pack, "audience")) == _union(b, _words_for(pack, "audience"))
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
    assert len(set(names)) == len(names)


def test_no_two_family_variants_render_to_the_same_sentence(pack):
    rendered = [render(v, SAMPLE) for f in pack.families for v in f.variants]
    duplicates = sorted({s for s in rendered if rendered.count(s) > 1})
    assert duplicates == []


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


def test_every_scene_leaves_at_least_seven_eligible_roles(pack):
    for scene in pack.scene_types:
        assert len(eligible_roles(pack, scene)) >= 7, scene.key


def test_no_hard_coded_record_name_is_left_in_the_families_or_the_presence_lines(pack):
    assert _found(_all_texts(pack), _record_names(pack)) == []


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


def test_the_five_new_families_exist_once_with_their_ids_kinds_and_slots(pack):
    for kind, slots in NEW_FAMILIES.items():
        family = _family_of_kind(pack, kind)
        assert family.id == kind
        assert set(family.claim_slots) == slots, kind
        assert len(family.variants) >= 7, kind
        for variant in family.variants:
            assert slots <= _slots(variant), variant


def test_the_two_physical_families_pair_up_variant_by_variant(pack):
    proof, clear = _family_of_kind(pack, "physical_proof"), _family_of_kind(pack, "physical_clear")
    assert len(proof.variants) == len(clear.variants)
    assert _union(proof.variants, _words_for(pack, "physical")) == _union(
        clear.variants, _words_for(pack, "physical")
    )
    assert _union(proof.variants, _words_for(pack, "witness")) == _union(
        clear.variants, _words_for(pack, "witness")
    )
    assert _union(proof.variants, _words_for(pack, "audience")) == _union(
        clear.variants, _words_for(pack, "audience")
    )
    for a, b in zip(proof.variants, clear.variants, strict=True):
        assert _slots(a) == _slots(b) == {"who", "record"}, (a, b)
        assert _union([a], _words_for(pack, "physical")) == _union(
            [b], _words_for(pack, "physical")
        ), (a, b)
    mean_proof = sum(len(render(t, SAMPLES[0])) for t in proof.variants) / len(proof.variants)
    mean_clear = sum(len(render(t, SAMPLES[0])) for t in clear.variants) / len(clear.variants)
    assert abs(mean_proof - mean_clear) <= 0.1 * max(mean_proof, mean_clear)


def test_the_physical_and_contradiction_texts_name_their_record_by_placeholder(pack):
    texts = [
        t
        for k in ("physical_proof", "physical_clear", "contradiction")
        for t in _family_of_kind(pack, k).variants
    ]
    assert _found(texts, _record_names(pack)) == []
    assert all("record" in _slots(t) for t in texts)


def test_the_physical_texts_state_no_place_and_no_time(pack):
    for kind in ("physical_proof", "physical_clear"):
        for variant in _family_of_kind(pack, kind).variants:
            assert not {"place", "place.in", "time.at", "time.phrase", "time.during"} & _slots(
                variant
            )


def test_the_intro_names_no_suspect_role_and_says_who_died_where_and_when(pack):
    roles = [r.key for r in pack.roles] + [r.noun for r in pack.roles]
    variants = _family_of_kind(pack, "intro").variants
    assert _found(variants, roles) == []
    for variant in variants:
        assert {"victim", "place.in", "time.during"} <= _slots(variant)
    named = token_set(
        *(x for d in (*pack.method_defs, *pack.motive_defs) for x in (d.label, *d.aliases))
    )
    for variant in variants:
        assert not token_set(blank_placeholders(variant)) & named, variant


def test_no_new_text_states_a_certainty_or_a_negation(pack):
    texts = _new_texts(pack)
    assert _found(texts, CERTAINTY_WORDS) == []
    assert _found(texts, NEGATIONS) == []


def test_every_new_text_is_one_sentence_ending_in_a_full_stop(pack):
    for text in _new_texts(pack):
        assert text.endswith(".") and text.count(". ") == 0, text


def test_no_two_new_texts_render_to_the_same_sentence(pack):
    rendered = [render(t, SAMPLE) for t in _new_texts(pack)]
    assert sorted({s for s in rendered if rendered.count(s) > 1}) == []


def test_every_new_text_renders_with_every_sample_to_a_clean_sentence(pack):
    for text in _new_texts(pack):
        assert set(placeholders(text)) <= KNOWN_PLACEHOLDERS, text
        for sample in (*SAMPLES, SAMPLE):
            out = render(text, sample)
            assert "{" not in out and "}" not in out and "  " not in out, (text, out)
            assert out[0].isupper(), (text, out)
            assert not re.search(r"\s[.,]", out), (text, out)


def test_a_wording_edit_keeps_the_skeleton_hash_and_dropping_a_family_changes_it(pack):
    hints = ("An edited hint.", *pack.motive_defs[0].hints[1:])
    motives = (pack.motive_defs[0].model_copy(update={"hints": hints}), *pack.motive_defs[1:])
    assert pack.model_copy(update={"motive_defs": motives}).skeleton_hash() == pack.skeleton_hash()
    kept = tuple(f for f in pack.families if f.kind != "intro")
    assert pack.model_copy(update={"families": kept}).skeleton_hash() != pack.skeleton_hash()


def test_absent_texts_and_clues_describe_objects_not_bodies(pack):
    owned = [t for p, t in _owned(pack) if ".absent[" in p or ".clues[" in p]
    assert owned and _found(owned, BODY_WORDS) == []


def test_every_method_has_as_many_absent_texts_as_templates_and_three_clues(pack):
    for method in pack.method_defs:
        for trace in method.traces:
            assert len(trace.absent) == len(trace.templates) == 2, method.key
        assert len(method.clues) == 3, method.key
        for text in (t for tr in method.traces for t in tr.absent):
            assert "place.in" in _slots(text), text
        for text in method.clues:
            assert "place.in" in _slots(text), text


def test_absent_texts_open_like_the_trace_templates(pack):
    openers = {t.split()[0] for m in pack.method_defs for tr in m.traces for t in tr.templates}
    for method in pack.method_defs:
        for trace in method.traces:
            for text in trace.absent:
                assert text.split()[0] in openers, (method.key, text)


def test_every_motive_has_three_hints_that_carry_no_place_or_time(pack):
    for motive in pack.motive_defs:
        assert len(motive.hints) == 3, motive.key
        for hint in motive.hints:
            assert set(PLACEHOLDER.findall(hint)) <= ALLOWED_SECRET_SLOTS, hint
            assert "who" in _slots(hint), hint
            assert hint not in motive.secrets, hint
            assert hint.startswith("{^who}") and hint.endswith("."), hint


def test_the_location_record_entries_are_neutral(pack):
    entries = [e for d in pack.record_defs if d.subject == "location" for e in d.entries]
    assert len(entries) >= 3
    for entry in entries:
        assert _slots(entry) <= {"record"}, entry
    suspect_entries = [e for d in pack.record_defs if d.subject != "location" for e in d.entries]
    assert suspect_entries == []


def test_every_role_has_its_own_style(pack):
    styles = [r.style for r in pack.roles]
    assert all(len(s) >= 10 for s in styles) and len(set(styles)) == len(styles)


@pytest.mark.parametrize("pack_id", [i.id for i in bundled_packs()])
def test_a_bundled_pack_loads_with_no_issues_under_the_real_presets(pack_id):
    raw = files("gumshoe.cases.packs").joinpath(f"{pack_id}.toml").read_bytes()
    result = load_pack(raw)
    assert [(i.code, i.path) for i in result.issues] == [] and result.pack is not None


def test_a_pack_claims_only_known_presets_and_fits_its_capacity_in_its_pools(pack):
    assert pack.presets and set(pack.presets) <= {"short", "standard", "long"}
    cap = pack.capacity
    assert cap.max_locations <= len(pack.location_defs)
    assert cap.max_methods <= len(pack.method_defs)
    assert cap.max_record_kinds <= len(pack.record_defs)
    assert cap.max_suspects <= len(pack.roles) and cap.max_suspects <= len(pack.motive_defs)


def _family_variants(pack: Pack, *ids: str) -> list[str]:
    return [v for f in pack.families if f.id in ids for v in f.variants]


@pytest.mark.parametrize(
    ("kind", "ids"),
    [
        ("witness", ("alibi", "lie_alibi", "presence_record", "lie_record")),
        ("audience", ("alibi", "lie_alibi", "presence_record", "lie_record")),
        ("physical", ("physical_proof", "physical_clear")),
    ],
)
def test_the_parity_word_lists_are_not_vacuous_on_a_pack(pack, kind, ids):
    texts = _family_variants(pack, *ids)
    hit = _union(texts, _words_for(pack, kind))
    assert len(hit) >= MIN_HITS, (
        f"the {kind} list matches only {sorted(hit)} in {pack.id}; "
        f"add this pack's words to WORDS_BY_PACK"
    )
