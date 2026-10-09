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
from gumshoe.cases.packs.check import templates
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
