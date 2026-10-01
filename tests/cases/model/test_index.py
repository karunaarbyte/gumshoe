from gumshoe.cases.model.entities import Fact, SourceRef
from gumshoe.cases.model.enums import Axis, FactKind, SourceKind
from gumshoe.cases.model.index import CaseIndex
from tests.cases.model.builders import tiny_case


def test_lookup_tables():
    ix = CaseIndex.of(tiny_case())
    assert set(ix.facts) == {"f_one", "f_two"}
    assert set(ix.suspects) == {"s_a", "s_b"} and set(ix.locations) == {"l_x"}
    assert (
        set(ix.methods) == {"m_x"}
        and set(ix.motives) == {"v_a", "v_b"}
        and set(ix.events) == {"t_1"}
    )
    assert set(ix.record_sources) == {("ledger", "s_a")}


def test_candidates_and_truth_per_axis():
    ix = CaseIndex.of(tiny_case())
    assert ix.candidates[Axis.WHO] == ("s_a", "s_b")
    assert ix.candidates[Axis.HOW] == ("m_x",)
    assert ix.candidates[Axis.WHY] == ("v_a", "v_b")
    assert (ix.truth(Axis.WHO), ix.truth(Axis.HOW), ix.truth(Axis.WHY)) == ("s_a", "m_x", "v_a")


def test_source_gate_comes_from_the_source_target():
    case = tiny_case()
    gated_loc = case.locations[0].model_copy(update={"requires": ("f_one",)})
    gated_sus = case.suspects[0].model_copy(update={"requires": ("f_two",)})
    gated_rs = case.record_sources[0].model_copy(update={"requires": ("f_one", "f_two")})
    case = case.model_copy(
        update={
            "locations": (gated_loc,),
            "suspects": (gated_sus, case.suspects[1]),
            "record_sources": (gated_rs,),
        }
    )
    ix = CaseIndex.of(case)
    assert ix.source_gate(SourceRef(kind=SourceKind.SEARCH, target="l_x")) == ("f_one",)
    assert ix.source_gate(SourceRef(kind=SourceKind.INTERROGATE, target="s_a")) == ("f_two",)
    assert ix.source_gate(SourceRef(kind=SourceKind.RECORD, target="ledger", subject="s_a")) == (
        "f_one",
        "f_two",
    )
    assert ix.source_gate(SourceRef(kind=SourceKind.SEARCH, target="l_missing")) == ()


def test_facts_at_a_source_and_deps():
    case = tiny_case()
    ix = CaseIndex.of(case)
    at_x = ix.facts_at(SourceRef(kind=SourceKind.SEARCH, target="l_x"))
    assert [f.id for f in at_x] == ["f_one"]
    gated = case.model_copy(
        update={"locations": (case.locations[0].model_copy(update={"requires": ("f_two",)}),)}
    )
    f_one = Fact(
        id="f_one",
        kind=FactKind.CLUE,
        source=SourceRef(kind=SourceKind.SEARCH, target="l_x"),
        requires=("f_two",),
    )
    ix2 = CaseIndex.of(gated.model_copy(update={"facts": (f_one, gated.facts[1])}))
    assert ix2.deps(ix2.facts["f_one"]) == frozenset({"f_two"})


def test_index_tolerates_duplicates_and_dangling_references():
    case = tiny_case()
    dup = case.model_copy(
        update={"facts": (*case.facts, case.facts[0].model_copy(update={"text": "dup"}))}
    )
    ix = CaseIndex.of(dup)
    assert set(ix.facts) == {"f_one", "f_two"}
    assert ix.source_gate(SourceRef(kind=SourceKind.RECORD, target="nope", subject="s_zzz")) == ()
