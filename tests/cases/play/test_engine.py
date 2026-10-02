from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.engine import (
    Contradiction,
    SourceStatus,
    all_sources,
    available_facts,
    exposer_of,
    record_kinds,
    use_source,
)
from gumshoe.cases.play.state import PlayState, Status, new_state
from tests.cases.fixtures import ask, build_case, record, search
from tests.cases.helpers import replace_fact, replace_record_source, replace_start


def setup(case=None, held=()):
    case = case or build_case()
    state = new_state(case)
    if held:
        state = state.with_facts(held)
    return CaseIndex.of(case), state


def test_a_new_state_holds_exactly_the_start_facts():
    case = replace_start(build_case(), facts=("f_key",))
    state = new_state(case)
    assert state.held == frozenset({"f_key"})
    assert state.attempts == 0 and state.accusations == () and state.status is Status.PLAYING


def test_with_facts_keeps_the_tuple_sorted_and_unique():
    state = PlayState(case_digest="d").with_facts(["f_b", "f_a", "f_b"])
    assert state.discovered == ("f_a", "f_b")


def test_a_search_returns_every_available_fact_in_id_order():
    ix, state = setup()
    state, out = use_source(ix, state, search("l_study"))
    assert out.status is SourceStatus.OK
    assert out.new_facts == ("f_absent_dagger", "f_absent_rope", "f_proof_boris", "f_trace_poison")
    assert state.discovered == out.new_facts
    assert out.opened == () and out.contradictions == ()


def test_using_a_source_again_is_idempotent():
    ix, state = setup()
    state, _ = use_source(ix, state, search("l_study"))
    again, out = use_source(ix, state, search("l_study"))
    assert out.status is SourceStatus.NOTHING_NEW and out.new_facts == ()
    assert again == state


def test_a_gated_location_is_locked_until_its_key_is_held_then_reported_as_opened():
    ix, state = setup()
    _, locked = use_source(ix, state, search("l_cellar"))
    assert locked.status is SourceStatus.LOCKED and locked.new_facts == ()
    state, garden = use_source(ix, state, search("l_garden"))
    assert garden.new_facts == ("f_alibi_anna", "f_key")
    assert garden.opened == (search("l_cellar"),)
    state, cellar = use_source(ix, state, search("l_cellar"))
    assert cellar.new_facts == ("f_clara_keys",)


def test_a_location_outside_start_without_a_gate_stays_locked():
    case = replace_start(build_case(), locations=("l_study",))
    ix, state = setup(case)
    _, out = use_source(ix, state, search("l_garden"))
    assert out.status is SourceStatus.LOCKED


def test_a_gated_record_source_is_locked_then_opens():
    case = replace_record_source(build_case(), "ledger", "s_boris", requires=("f_key",))
    ix, state = setup(case)
    _, locked = use_source(ix, state, record("ledger", "s_boris"))
    assert locked.status is SourceStatus.LOCKED
    state, garden = use_source(ix, state, search("l_garden"))
    assert record("ledger", "s_boris") in garden.opened
    _, opened = use_source(ix, state, record("ledger", "s_boris"))
    assert opened.new_facts == ("f_secret_boris",)


def test_unknown_entities_are_unknown_and_an_undeclared_pair_is_just_empty():
    ix, state = setup()
    assert use_source(ix, state, search("l_nowhere"))[1].status is SourceStatus.UNKNOWN
    assert use_source(ix, state, ask("s_ghost"))[1].status is SourceStatus.UNKNOWN
    assert use_source(ix, state, record("gate_log", "s_ghost"))[1].status is SourceStatus.UNKNOWN
    assert use_source(ix, state, record("nonsense", "s_anna"))[1].status is SourceStatus.UNKNOWN
    # a known kind about a known subject with no declared pair: nothing, never "unknown"
    assert use_source(ix, state, record("gate_log", "s_anna"))[1].status is SourceStatus.NOTHING_NEW


def test_facts_with_unmet_requires_wait_and_the_source_is_reported_when_they_free_up():
    case = replace_fact(build_case(), "f_sup_boris", requires=("f_key",))
    ix, state = setup(case)
    state, first = use_source(ix, state, ask("s_anna"))
    assert first.new_facts == ("f_lie_anna",)
    state, garden = use_source(ix, state, search("l_garden"))
    assert garden.opened == (ask("s_anna"), search("l_cellar"))
    _, second = use_source(ix, state, ask("s_anna"))
    assert second.new_facts == ("f_sup_boris",)


def test_contradiction_when_the_exposer_comes_first_is_emitted_at_the_lie():
    ix, state = setup()
    state, first = use_source(ix, state, record("ledger", "s_anna"))
    assert first.contradictions == ()
    state, second = use_source(ix, state, ask("s_anna"))
    assert second.contradictions == (Contradiction(lie="f_lie_anna", exposer="f_secret_anna"),)


def test_contradiction_when_the_lie_comes_first_is_emitted_at_the_exposer():
    ix, state = setup()
    state, first = use_source(ix, state, ask("s_anna"))
    assert first.contradictions == ()
    state, second = use_source(ix, state, record("ledger", "s_anna"))
    assert second.contradictions == (Contradiction(lie="f_lie_anna", exposer="f_secret_anna"),)
    _, third = use_source(ix, state, record("ledger", "s_anna"))
    assert third.contradictions == ()  # emitted once


def test_all_sources_and_record_kinds_are_neutral_and_sorted():
    ix, _ = setup()
    assert record_kinds(ix) == ("gate_log", "ledger")
    sources = all_sources(ix)
    assert len(sources) == len(set(sources)) == 11
    assert search("l_study") in sources and record("gate_log", "l_garden") in sources


def test_available_facts_is_empty_for_a_closed_source():
    ix, state = setup()
    assert available_facts(ix, state.held, search("l_cellar")) == ()


def test_ghost_start_facts_are_filtered_by_new_state():
    case = replace_start(build_case(), facts=("f_key", "f_ghost"))
    assert new_state(case).held == frozenset({"f_key"})


def test_a_duplicated_lie_fact_with_no_held_exposer_does_not_crash_use_source():
    case = build_case()
    lie = next(f for f in case.facts if f.id == "f_lie_anna")
    ghost_twin = lie.model_copy(update={"exposed_by": ("f_nowhere",)})
    case = case.model_copy(update={"facts": (*case.facts, ghost_twin)})
    ix, state = setup(case)
    for source in all_sources(ix):
        state, _ = use_source(ix, state, source)
        state, _ = use_source(ix, state, source)


def test_a_chain_inside_one_source_is_gathered_in_a_single_use():
    # spec 5.3: one use returns ALL newly available facts, even one that needs another fact
    # found in the same sitting
    case = replace_fact(build_case(), "f_sup_boris", requires=("f_lie_anna",))
    ix, state = setup(case)
    state, first = use_source(ix, state, ask("s_anna"))
    assert first.status is SourceStatus.OK
    assert first.new_facts == ("f_lie_anna", "f_sup_boris")
    assert ask("s_anna") not in first.opened  # exhausted by the call, never "opened" for itself
    again, second = use_source(ix, state, ask("s_anna"))
    assert second.status is SourceStatus.NOTHING_NEW and again == state


def test_a_chain_does_not_reach_into_other_sources():
    # f_key (garden) frees the cellar, but the cellar is another source: reported, not read
    ix, state = setup()
    state, garden = use_source(ix, state, search("l_garden"))
    assert "f_clara_keys" not in garden.new_facts and garden.opened == (search("l_cellar"),)


def test_exposer_of_picks_the_smallest_held_exposer():
    case = replace_fact(build_case(), "f_lie_anna", exposed_by=("f_secret_anna", "f_key"))
    ix, _ = setup(case)
    assert exposer_of(ix, "f_lie_anna", frozenset({"f_secret_anna", "f_key"})) == "f_key"
    assert exposer_of(ix, "f_lie_anna", frozenset({"f_secret_anna"})) == "f_secret_anna"
