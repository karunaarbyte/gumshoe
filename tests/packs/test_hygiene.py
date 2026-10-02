from gumshoe.cases.model.pack import MethodDef, MotiveDef, Pack, TraceDef
from gumshoe.cases.packs.check import hygiene
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
