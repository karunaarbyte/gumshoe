import pytest

from gumshoe.cases.model.pack import Entry, MethodDef, MotiveDef, Pack, TraceDef
from gumshoe.cases.packs.check import hygiene
from gumshoe.cases.tools.builtin import load_builtin_pack
from tests.packs.fixtures import rich_pack


def found(pack):
    return [(i.code, i.path) for i in hygiene.check(pack)]


def _two_methods(trait: str):
    methods = (
        MethodDef(
            key="dagger",
            label="stabbed with a dagger",
            aliases=("blade",),
            traces=(
                TraceDef(kind="wound", location_kinds=("study",), templates=("A cut {place.in}.",)),
            ),
        ),
        MethodDef(
            key="poison",
            label="poisoned in the wine",
            traces=(
                TraceDef(
                    kind="residue", location_kinds=("study",), templates=("A film {place.in}.",)
                ),
            ),
        ),
    )
    role = rich_pack().roles[0].model_copy(update={"traits": (trait,)})
    return rich_pack(method_defs=methods, roles=(role,))


def test_a_clean_pack_has_no_hygiene_issues():
    assert found(_two_methods("quiet")) == []


def test_a_candidate_token_in_foreign_text_is_a_leak_naming_the_candidate_and_path():
    (issue,) = hygiene.check(_two_methods("sharp as a blade"))
    assert issue.code == "LABEL_TOKEN_LEAK" and issue.path == "roles.maid.traits[0]"
    assert "method:dagger" in issue.message and "'blad'" in issue.message


def test_the_leak_is_found_in_any_case_and_in_decomposed_unicode():
    methods = (
        MethodDef(key="a", label="stabbed with an épée", aliases=()),
        MethodDef(key="b", label="poisoned in the wine"),
    )
    for trait in ("QUITE THE ÉPÉE", "an épée hangs here", "an épée hangs here"):
        role = rich_pack().roles[0].model_copy(update={"traits": (trait,)})
        assert [c for c, _ in found(rich_pack(method_defs=methods, roles=(role,)))] == [
            "LABEL_TOKEN_LEAK"
        ], trait


def test_a_motives_own_secret_may_not_reuse_its_label():
    pack = rich_pack(
        motive_defs=(
            MotiveDef(
                key="debt", label="to cover a gambling debt", secrets=("{^who} hid the debt.",)
            ),
        )
    )
    assert found(pack) == [("SECRET_REUSES_LABEL", "motive_defs.debt.secrets[0]")]


def test_tokens_shared_by_two_candidates_are_not_distinctive():
    methods = (
        MethodDef(key="a", label="a poisoned cup"),
        MethodDef(key="b", label="a poisoned dart"),
    )
    role = rich_pack().roles[0].model_copy(update={"traits": ("fond of poison",)})
    assert found(rich_pack(method_defs=methods, roles=(role,))) == []  # "poison" is shared


def test_trace_counts_must_match_and_lengths_stay_within_twenty_percent():
    def trace(*texts):
        return (TraceDef(kind="k", location_kinds=("study",), templates=texts),)

    even = (
        MethodDef(key="a", label="alpha", traces=trace("x" * 60, "y" * 60)),
        MethodDef(key="b", label="beta", traces=trace("z" * 60, "w" * 60)),
    )
    assert found(rich_pack(method_defs=even)) == []
    uneven = (even[0], MethodDef(key="b", label="beta", traces=trace("z" * 60)))
    assert found(rich_pack(method_defs=uneven)) == [("TRACE_COUNT_SKEW", "method_defs.b")]
    long_one = (even[0], MethodDef(key="b", label="beta", traces=trace("z" * 100, "w" * 100)))
    assert {p for c, p in found(rich_pack(method_defs=long_one)) if c == "TRACE_LENGTH_SKEW"} == {
        "method_defs.a",
        "method_defs.b",
    }


def test_nothing_declared_means_nothing_to_check():
    assert hygiene.check(Pack(id="e", capacity=rich_pack().capacity)) == []
    assert hygiene.check(rich_pack(method_defs=(), motive_defs=())) == []


def test_placeholder_names_are_not_text_and_odd_input_is_total():
    methods = (
        MethodDef(key="a", label="place", traces=(TraceDef(kind="k", templates=("",)),)),
        MethodDef(key="b", label="", traces=(TraceDef(kind="k", templates=("{place}",)),)),
    )
    assert [c for c, _ in found(rich_pack(method_defs=methods))] == ["TRACE_LENGTH_SKEW"] * 2


def test_a_trait_is_tokenised_raw_so_braces_do_not_hide_a_leak():
    (issue,) = hygiene.check(_two_methods("handy with {dagger}"))
    assert (issue.code, issue.path) == ("LABEL_TOKEN_LEAK", "roles.maid.traits[0]")


def test_a_placeholder_in_a_template_splits_the_words_around_it():
    methods = _two_methods("quiet").method_defs
    poison = methods[1].model_copy(
        update={
            "traces": (
                TraceDef(kind="residue", location_kinds=("study",), templates=("bla{place}de",)),
            )
        }
    )
    # "bla de", not the dagger's "blade"
    assert found(rich_pack(method_defs=(methods[0], poison))) == []


def test_a_record_name_that_uses_a_candidate_token_is_a_leak():
    record = (
        rich_pack()
        .record_defs[0]
        .model_copy(update={"names": (Entry(text="poison book", article="the"),)})
    )
    issues = hygiene.check(rich_pack(record_defs=(record,)))
    assert [(i.code, i.path) for i in issues] == [
        ("LABEL_TOKEN_LEAK", "record_defs.ledger.names[0]")
    ]


def test_a_role_noun_sharing_a_non_distinctive_candidate_token_collides():
    # "out" is in every "out of ..." motive label, so it is not distinctive, but the case
    # validator's LABEL_NAME_COLLISION uses all tokens
    motives = (
        MotiveDef(key="a", label="out of fear"),
        MotiveDef(key="b", label="out of envy"),
    )
    role = rich_pack().roles[0].model_copy(update={"noun": "look-out"})
    issues = hygiene.check(rich_pack(motive_defs=motives, roles=(role,)))
    assert [(i.code, i.path) for i in issues if i.code == "ROLE_TOKEN_COLLISION"] == [
        ("ROLE_TOKEN_COLLISION", "roles.maid.noun")
    ]


def test_two_roles_may_not_share_a_noun_token():
    first = rich_pack().roles[0]
    second = first.model_copy(update={"key": "steward", "noun": "Maid"})  # case differs
    issues = hygiene.check(rich_pack(roles=(first, second)))
    assert ("ROLE_TOKEN_COLLISION", "roles.steward.noun") in [(i.code, i.path) for i in issues]


def test_role_name_tokens_collide_with_candidate_tokens_in_any_case_or_unicode_form():
    method = MethodDef(key="m", label="poisoned in the wine", aliases=("poison",))
    name = Entry(text="POISON", proper=True)  # upper case
    role = rich_pack().roles[0].model_copy(update={"names": (name,)})
    issues = hygiene.check(rich_pack(method_defs=(method,), roles=(role,)))
    assert ("ROLE_TOKEN_COLLISION", "roles.maid.names[0]") in [(i.code, i.path) for i in issues]
    decomposed = Entry(text="e\u0301pe\u0301e")  # decomposed Unicode: e + combining accent
    epee = MethodDef(key="e", label="stabbed with an \u00e9p\u00e9e")  # composed form
    role2 = rich_pack().roles[0].model_copy(update={"names": (decomposed,)})
    got = hygiene.check(rich_pack(method_defs=(epee,), roles=(role2,)))
    assert ("ROLE_TOKEN_COLLISION", "roles.maid.names[0]") in [(i.code, i.path) for i in got]


def test_a_pack_with_no_roles_has_no_role_collisions():
    assert hygiene.check(Pack(id="e", capacity=rich_pack().capacity)) == []


def test_names_equal_after_unicode_normalisation_and_case():
    assert hygiene.same_name("Zo\u00e9", "Zoe\u0301")
    assert hygiene.same_name("Maud", "maud")
    assert not hygiene.same_name("Maud", "Maude")


def _first(items, **update):
    return (items[0].model_copy(update=update), *items[1:])


def _with_scene(**update):
    return lambda pack: pack.model_copy(update={"scene_types": _first(pack.scene_types, **update)})


def _with_role(**update):
    return lambda pack: pack.model_copy(update={"roles": _first(pack.roles, **update)})


def _with_trace(pack):
    method = pack.method_defs[0]
    trace = method.traces[0]
    trace = trace.model_copy(
        update={"location_kinds": (*trace.location_kinds, trace.location_kinds[0])}
    )
    method = method.model_copy(update={"traces": (trace, *method.traces[1:])})
    return pack.model_copy(update={"method_defs": (method, *pack.method_defs[1:])})


def _with_record(pack):
    record = pack.record_defs[0]
    kinds = (*record.location_kinds, record.location_kinds[0])
    record = record.model_copy(update={"location_kinds": kinds})
    return pack.model_copy(update={"record_defs": (record, *pack.record_defs[1:])})


def _doubled(items):
    return (*items, items[0])


_SITES = {
    "scene_types.murder_in_chapel.location_kinds": _with_scene(location_kinds=("chapel", "chapel")),
    "scene_types.murder_in_chapel.allowed_methods": lambda pack: _with_scene(
        allowed_methods=_doubled(pack.scene_types[0].allowed_methods)
    )(pack),
    "scene_types.murder_in_chapel.allowed_trace_kinds": lambda pack: _with_scene(
        allowed_trace_kinds=_doubled(pack.scene_types[0].allowed_trace_kinds)
    )(pack),
    "roles.bard.record_kinds": lambda pack: _with_role(
        record_kinds=_doubled(pack.roles[0].record_kinds)
    )(pack),
    "roles.bard.motive_types": lambda pack: _with_role(
        motive_types=_doubled(pack.roles[0].motive_types)
    )(pack),
}


@pytest.mark.parametrize("path", sorted(_SITES))
def test_a_repeated_entry_is_reported_at_each_scan_site(path):
    pack = _SITES[path](load_builtin_pack("castle"))
    assert [(i.code, i.path) for i in hygiene.duplicate_problems(pack)] == [
        ("DUPLICATE_ENTRY", path)
    ]


def test_a_repeated_entry_in_a_trace_and_in_a_record_def_is_reported():
    castle = load_builtin_pack("castle")
    (trace_issue,) = hygiene.duplicate_problems(_with_trace(castle))
    assert trace_issue.code == "DUPLICATE_ENTRY"
    method = castle.method_defs[0]
    assert trace_issue.path == (
        f"method_defs.{method.key}.traces[{method.traces[0].kind}].location_kinds"
    )
    (record_issue,) = hygiene.duplicate_problems(_with_record(castle))
    assert record_issue.path == f"record_defs.{castle.record_defs[0].key}.location_kinds"


def test_a_victim_named_like_a_role_is_a_duplicate_reported_once_at_the_victim():
    castle = load_builtin_pack("castle")
    bard = castle.roles[0].names[0]
    victims = (bard, *castle.victims[1:])
    issues = hygiene.name_problems(castle.model_copy(update={"victims": victims}))
    assert [(i.code, i.path) for i in issues] == [("NAME_DUPLICATE", "victims[0]")]
