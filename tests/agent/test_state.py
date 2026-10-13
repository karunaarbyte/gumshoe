from gumshoe.agent.config import AgentConfig
from gumshoe.agent.state import build_state, cap_facts
from gumshoe.cases import (
    NotebookFact,
    NotebookView,
    PlayerCaseView,
)
from gumshoe.cases.play.views import LocationView, NotebookSection, SuspectView


def fact(n, contradicted=False):
    return NotebookFact(
        handle=f"h_f{n}", text=f"fact {n}", speaker=None, relates_to=(), contradicted=contradicted
    )


def notebook(facts):
    return NotebookView(
        sections=(NotebookSection(source="Cellar", facts=tuple(facts)),), contradictions=()
    )


def brief():
    return PlayerCaseView(
        intro="A castle.",
        locations=(
            LocationView(number=1, handle="h_l1", name="The cellar", description="d", locked=False),
            LocationView(number=2, handle="h_l2", name="The tower", description="d", locked=True),
        ),
        suspects=(
            SuspectView(
                number=1, handle="h_s1", name="Berta the cook", description="d", locked=False
            ),
        ),
        record_kinds=(),
        attempts_left=3,
        status="playing",
    )


def test_cap_keeps_every_contradicted_fact_and_the_last_n_in_notebook_order():
    facts = [fact(i, contradicted=(i == 2)) for i in range(10)]
    kept = cap_facts(notebook(facts), 3)
    assert [f.text for f in kept] == ["fact 2", "fact 7", "fact 8", "fact 9"]


def test_cap_keeps_everything_when_small():
    assert len(cap_facts(notebook([fact(0), fact(1)]), 30)) == 2


def test_state_starts_with_the_player_text_and_lists_places_and_suspects_by_key():
    state = build_state(
        text="search the cellar",
        pending_line=None,
        exchanges=[],
        brief=brief(),
        notebook=notebook([fact(1)]),
        config=AgentConfig(),
    )
    assert state.splitlines()[0] == "Player says: search the cellar"
    assert "place_1: The cellar" in state and "place_2: The tower (locked)" in state
    assert "suspect_1: Berta the cook" in state
    assert "fact 1" in state


def test_state_shows_the_pending_confirmation_and_only_the_last_exchanges():
    exchanges = [("q1", "a1"), ("q2", "a2"), ("q3", "a3")]
    state = build_state(
        text="yes",
        pending_line="Your accusation: A / B / C. Confirm?",
        exchanges=exchanges,
        brief=brief(),
        notebook=notebook([]),
        config=AgentConfig(exchanges_kept=2),
    )
    assert "Waiting for the player to confirm: Your accusation: A / B / C. Confirm?" in state
    assert "q1" not in state and "q2" in state and "q3" in state


def test_state_never_contains_a_handle_of_a_fact_or_an_unfound_secret():
    state = build_state(
        text="x",
        pending_line=None,
        exchanges=[],
        brief=brief(),
        notebook=notebook([fact(1)]),
        config=AgentConfig(),
    )
    assert "h_f1" not in state and "h_l1" not in state and "h_s1" not in state
