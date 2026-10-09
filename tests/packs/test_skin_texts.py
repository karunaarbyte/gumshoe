"""The wording fields of a pack: model, loader, hash, and the stage 3 and 4 checks on them."""

from gumshoe.cases.model.pack import (
    Entry,
    MethodDef,
    MotiveDef,
    Pack,
    RecordDef,
    RoleDef,
    TraceDef,
)
from gumshoe.cases.packs.check import hygiene, templates
from gumshoe.cases.packs.check.lint import KNOWN_PLACEHOLDERS, SAMPLES, pack_sample
from gumshoe.cases.packs.issues import PackIssue
from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS

MINIMAL = """\
[meta]
id = "m"
smalltalk_allow = ["soup", "ale", "bread"]

[capacity]
max_suspects = 3
max_locations = 3
max_methods = 3
max_record_kinds = 2

[[victims]]
text = "Lord Aldric"
pronoun = "he"
proper = true

[record_defs.gate_log]
subject = "location"
medium = "written"
entries = ["{^record} lay open."]

[method_defs.dagger]
label = "stabbed with a dagger"
clues = ["A whetstone {place.in} was wet."]

[[method_defs.dagger.traces]]
kind = "wound"
absent = ["The floor {place.in} was clean."]

[motive_defs.debt]
label = "to cover a gambling debt"
hints = ["{^who} avoided the pedlars."]

[roles.maid]
style = "quick and chatty"
"""


def base() -> Pack:
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    assert pack is not None
    return pack


def found(issues: list[PackIssue]) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in issues]


def with_method(pack: Pack, key: str, **changes: object) -> Pack:
    methods = tuple(m.model_copy(update=changes) if m.key == key else m for m in pack.method_defs)
    return pack.model_copy(update={"method_defs": methods})


def with_trace(pack: Pack, key: str, **changes: object) -> Pack:
    def edit(method: MethodDef) -> MethodDef:
        trace = method.traces[0].model_copy(update=changes)
        return method.model_copy(update={"traces": (trace,)})

    methods = tuple(edit(m) if m.key == key else m for m in pack.method_defs)
    return pack.model_copy(update={"method_defs": methods})


def with_motive(pack: Pack, key: str, **changes: object) -> Pack:
    motives = tuple(m.model_copy(update=changes) if m.key == key else m for m in pack.motive_defs)
    return pack.model_copy(update={"motive_defs": motives})


def with_victims(pack: Pack, *names: str) -> Pack:
    victims = tuple(Entry(text=n, pronoun="he", proper=True) for n in names)
    return pack.model_copy(update={"victims": victims})


# ---- model and loader ----------------------------------------------------------------------


def test_every_new_field_defaults_to_empty():
    pack = Pack(id="x", capacity=base().capacity)
    assert pack.victims == () and pack.smalltalk_allow == ()
    assert RoleDef(key="r").style == ""
    assert MethodDef(key="m", label="l").clues == ()
    assert MotiveDef(key="m", label="l").hints == ()
    assert RecordDef(key="r", subject="suspect", medium="written").entries == ()
    assert TraceDef(kind="k").absent == ()


def test_every_new_field_loads_from_toml():
    pack = load_pack(MINIMAL.encode(), TEST_PRESETS).pack
    assert pack is not None
    assert [v.text for v in pack.victims] == ["Lord Aldric"] and pack.victims[0].pronoun == "he"
    assert pack.smalltalk_allow == ("ale", "bread", "soup")  # a set: sorted
    assert pack.record_defs[0].entries == ("{^record} lay open.",)
    assert pack.method_defs[0].clues == ("A whetstone {place.in} was wet.",)
    assert pack.method_defs[0].traces[0].absent == ("The floor {place.in} was clean.",)
    assert pack.motive_defs[0].hints == ("{^who} avoided the pedlars.",)
    assert pack.roles[0].style == "quick and chatty"


def test_an_unknown_key_in_a_victim_is_refused_with_a_key_path():
    text = MINIMAL.replace("proper = true\n", 'proper = true\ncolour = "red"\n')
    result = load_pack(text.encode(), TEST_PRESETS)
    assert result.pack is None
    assert found(list(result.issues)) == [("UNKNOWN_KEY", "victims[0].colour")]


def test_wrong_types_in_the_new_fields_are_wrong_type_issues_with_paths():
    cases = {
        'smalltalk_allow = ["soup", "ale", "bread"]': (
            'smalltalk_allow = "soup"',
            "meta.smalltalk_allow",
        ),
        'text = "Lord Aldric"': ("text = 5", "victims[0].text"),
        'absent = ["The floor {place.in} was clean."]': (
            'absent = "clean"',
            "method_defs.dagger.traces[0].absent",
        ),
        'style = "quick and chatty"': ("style = 3", "roles.maid.style"),
    }
    for old, (new, path) in cases.items():
        result = load_pack(MINIMAL.replace(old, new).encode(), TEST_PRESETS)
        assert result.pack is None, old
        assert found(list(result.issues)) == [("WRONG_TYPE", path)], old


def test_a_victim_needs_a_pronoun_from_the_known_set():
    text = MINIMAL.replace('pronoun = "he"', 'pronoun = "xe"')
    result = load_pack(text.encode(), TEST_PRESETS)
    assert result.pack is None
    assert found(list(result.issues)) == [("WRONG_TYPE", "victims[0].pronoun")]


# ---- placeholders and samples ---------------------------------------------------------------


def test_the_victim_placeholders_are_known_and_every_sample_has_them():
    names = {"victim", "victim.subj", "victim.poss"}
    assert names <= KNOWN_PLACEHOLDERS
    for sample in SAMPLES:
        assert names <= set(sample)


def test_the_pack_sample_takes_the_victim_from_the_first_victim():
    lady = Entry(text="Lady Maud", pronoun="she", proper=True)
    sample = pack_sample(base().model_copy(update={"victims": (lady,)}))
    assert (sample["victim"], sample["victim.subj"], sample["victim.poss"]) == (
        "Lady Maud",
        "she",
        "her",
    )
    bare = pack_sample(base().model_copy(update={"victims": ()}))
    assert bare["victim"] == SAMPLES[0]["victim"]


def test_a_variant_using_the_victim_placeholders_is_a_valid_template():
    text = "{^victim} died {place.in}, and {victim.poss} heir wept for {victim.subj}."
    assert templates.lint_template("p", text) == []


# ---- the hash ignores the new wording -------------------------------------------------------


def test_the_skeleton_hash_ignores_every_new_wording_field():
    pack = base()
    same = with_motive(pack, "debt", hints=("Another hint.", "And another.", "And a third."))
    same = with_method(same, "rope", clues=("a", "b", "c"))
    same = with_trace(same, "dagger", absent=("One.", "Two."))
    same = with_victims(same, "Lord Zed").model_copy(update={"smalltalk_allow": ("zzz",)})
    assert same.skeleton_hash() == pack.skeleton_hash()


def test_the_skeleton_hash_changes_when_a_family_is_added():
    pack = base()
    fewer = pack.model_copy(update={"families": pack.families[:-1]})
    assert fewer.skeleton_hash() != pack.skeleton_hash()


# ---- stage 3 reaches the new texts ----------------------------------------------------------


def test_a_doubled_word_in_an_absent_text_is_reported_at_its_path():
    pack = with_trace(base(), "dagger", absent=("The the floor {place.in} was clean.",))
    assert ("DOUBLED_WORD", "method_defs.dagger.traces[wound].absent[0]") in found(
        templates.check(pack)
    )


def test_an_unknown_placeholder_in_a_clue_is_reported():
    pack = with_method(base(), "rope", clues=("A {plce} was wet.",))
    assert ("UNKNOWN_PLACEHOLDER", "method_defs.rope.clues[0]") in found(templates.check(pack))


def test_an_article_mismatch_in_a_hint_is_reported():
    pack = with_motive(base(), "debt", hints=("{^who} ate a apple.",))
    assert ("ARTICLE_MISMATCH", "motive_defs.debt.hints[0]") in found(templates.check(pack))


def test_a_double_space_in_a_record_entry_is_reported():
    records = tuple(
        r.model_copy(update={"entries": ("{^record}  lay open.",)}) if r.key == "gate_log" else r
        for r in base().record_defs
    )
    pack = base().model_copy(update={"record_defs": records})
    assert ("DOUBLE_SPACE", "record_defs.gate_log.entries[0]") in found(templates.check(pack))


def test_a_victim_and_a_style_are_linted_as_pool_texts():
    pack = with_victims(base(), "Lord  Aldric")
    assert ("DOUBLE_SPACE", "victims[0]") in found(templates.check(pack))
    roles = tuple(
        r.model_copy(update={"style": "quick {and chatty"}) if r.key == "maid" else r
        for r in base().roles
    )
    pack = base().model_copy(update={"roles": roles})
    assert ("UNRESOLVED_BRACE", "roles.maid.style") in found(templates.check(pack))


# ---- stage 4 leak-scans the new texts -------------------------------------------------------


def test_another_methods_token_in_a_clue_or_an_absent_text_is_a_leak():
    pack = with_method(base(), "rope", clues=("A knife lay {place.in}.",))
    assert ("LABEL_TOKEN_LEAK", "method_defs.rope.clues[0]") in found(hygiene.check(pack))
    pack = with_trace(base(), "dagger", absent=("The rope {place.in} was clean.", "Fine."))
    assert ("LABEL_TOKEN_LEAK", "method_defs.dagger.traces[wound].absent[0]") in found(
        hygiene.check(pack)
    )


def test_a_methods_own_token_in_its_own_clue_is_allowed():
    pack = with_method(base(), "dagger", clues=("A knife lay {place.in}.",) * 3)
    assert [p for c, p in found(hygiene.check(pack)) if c == "LABEL_TOKEN_LEAK"] == []


def test_a_hint_reusing_its_own_label_token_is_reported_with_the_secret_code():
    pack = with_motive(base(), "debt", hints=("{^who} hid a debt.",) * 3)
    assert ("SECRET_REUSES_LABEL", "motive_defs.debt.hints[0]") in found(hygiene.check(pack))


def test_another_motives_token_in_a_hint_is_a_leak():
    pack = with_motive(base(), "debt", hints=("{^who} felt envy.",) * 3)
    assert ("LABEL_TOKEN_LEAK", "motive_defs.debt.hints[0]") in found(hygiene.check(pack))


def test_a_style_and_an_entry_are_leak_scanned():
    roles = tuple(
        r.model_copy(update={"style": "likes a dagger"}) if r.key == "maid" else r
        for r in base().roles
    )
    pack = base().model_copy(update={"roles": roles})
    assert ("LABEL_TOKEN_LEAK", "roles.maid.style") in found(hygiene.check(pack))
    records = tuple(
        r.model_copy(update={"entries": ("A rope lay by {record}.",)}) if r.key == "gate_log" else r
        for r in base().record_defs
    )
    pack = base().model_copy(update={"record_defs": records})
    assert ("LABEL_TOKEN_LEAK", "record_defs.gate_log.entries[0]") in found(hygiene.check(pack))


def test_a_victim_named_like_a_candidate_a_role_name_or_a_role_noun_is_reported():
    for name in ("Lord Dagger", "Lord Edmund", "Lord Steward"):
        pack = with_victims(base(), name)
        assert ("ROLE_TOKEN_COLLISION", "victims[0]") in found(hygiene.check(pack)), name
    assert ("LABEL_TOKEN_LEAK", "victims[0]") in found(
        hygiene.check(with_victims(base(), "Lord Dagger"))
    )
    assert [p for c, p in found(hygiene.check(with_victims(base(), "Lord Aldric")))] == []


def test_the_clean_skin_base_has_no_stage_3_or_4_issues():
    assert templates.check(base()) == [] and hygiene.check(base()) == []
