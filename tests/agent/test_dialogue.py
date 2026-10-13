import pytest

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.dialogue import (
    canned_line,
    draft_reply,
    evidence_against,
    persona_system,
    post_check,
)
from gumshoe.agent.llm import LlmError, LlmMessage
from gumshoe.cases import NotebookFact, NotebookView, PersonaBrief
from gumshoe.cases.play.views import ContradictionView, NotebookSection
from gumshoe.decider import DeciderConnectionError
from tests.agent.fakes import Script, ScriptedLlm
from tests.agent.harness import playing
from tests.mcp_server.helpers import castle_case

PERSONA = PersonaBrief(
    name="Berta the cook",
    traits=("blunt", "proud"),
    style="short, gruff sentences",
    says=("I was in the kitchen all evening.",),
    smalltalk_allow=("Hmm", "Well"),
)


def test_the_canned_line_uses_the_first_smalltalk_word():
    assert canned_line(PERSONA) == 'Berta the cook looks away and says only: "Hmm."'
    assert 'only: "Nothing."' in canned_line(PERSONA.model_copy(update={"smalltalk_allow": ()}))


def test_the_system_prompt_carries_the_persona_and_only_what_the_suspect_has_said():
    prompt = persona_system(PERSONA, ["The lamp was found broken."])
    assert "Berta the cook" in prompt and "short, gruff sentences" in prompt
    assert "blunt, proud" in prompt and "I was in the kitchen all evening." in prompt
    assert "The lamp was found broken." in prompt and "Hmm, Well" in prompt
    assert "none yet" in persona_system(PERSONA.model_copy(update={"says": ()}), [])


def test_evidence_is_the_contradictions_whose_lie_was_said_by_this_suspect():
    def f(h, speaker):
        return NotebookFact(handle=h, text=h, speaker=speaker, relates_to=(), contradicted=True)

    nb = NotebookView(
        sections=(
            NotebookSection(source="s", facts=(f("h_a", "Berta the cook"), f("h_b", "Piers"))),
        ),
        contradictions=(
            ContradictionView(lie="h_a", exposer="h_x", text="Berta's alibi fails."),
            ContradictionView(lie="h_b", exposer="h_x", text="Piers' alibi fails."),
        ),
    )
    assert evidence_against("Berta the cook", nb) == ["Berta's alibi fails."]


async def first_suspect(h):
    suspect = h.brief.suspects[0]
    persona = await h.deps.client.persona_brief(h.ctx.game, suspect.handle)
    return suspect.handle, persona


async def test_a_clean_first_draft_is_the_reply():
    llm = ScriptedLlm(["I was in the hall."])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="Where were you?",
            history=[],
            model="m",
            evidence=[],
        )
    assert (draft.text, draft.source, draft.degraded, draft.check_ok) == (
        "I was in the hall.",
        "draft",
        False,
        True,
    )
    assert len(llm.calls) == 1 and llm.calls[0][0] == "m"


async def test_a_draft_naming_an_unmet_method_is_redrafted_and_never_returned():
    case = castle_case(1)
    method = next(m.label for m in case.methods if m.id == case.truth.how)
    llm = ScriptedLlm([f"It was {method}!", "I was in the hall."])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="Well?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.text == "I was in the hall." and draft.source == "draft"
    assert len(llm.calls) == 2
    retry_system = llm.calls[1][1]
    assert "how" in retry_system and method not in retry_system  # categories, never the text


async def test_three_bad_drafts_and_then_one_more_end_in_the_canned_line():
    case = castle_case(1)
    method = next(m.label for m in case.methods if m.id == case.truth.how)
    llm = ScriptedLlm([f"It was {method}!"] * 4)
    async with playing(Script(), llm, config=AgentConfig(max_redrafts=3)) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="Well?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.source == "canned" and draft.degraded is False
    assert draft.text == canned_line(persona) and method not in draft.text
    assert len(llm.calls) == 4  # one draft plus three redrafts


async def test_zero_redrafts_means_one_attempt():
    case = castle_case(1)
    method = next(m.label for m in case.methods if m.id == case.truth.how)
    llm = ScriptedLlm([f"It was {method}!"])
    async with playing(Script(), llm, config=AgentConfig(max_redrafts=0)) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.source == "canned" and len(llm.calls) == 1


async def test_an_empty_draft_counts_as_a_failed_attempt():
    llm = ScriptedLlm(["   ", "I was in the hall."])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.text == "I was in the hall."


async def test_an_overlong_draft_is_truncated_not_refused():
    llm = ScriptedLlm(["a" * 5000])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.source == "draft" and len(draft.text) == 4000


async def test_an_llm_failure_is_the_canned_line_marked_degraded():
    llm = ScriptedLlm([LlmError("down")])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        draft = await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="?",
            history=[],
            model="m",
            evidence=[],
        )
    assert draft.source == "canned" and draft.degraded is True


async def test_history_becomes_alternating_messages_before_the_player_text():
    llm = ScriptedLlm(["ok"])
    async with playing(Script(), llm) as h:
        handle, persona = await first_suspect(h)
        await draft_reply(
            h.deps,
            game=h.ctx.game,
            suspect=handle,
            persona=persona,
            player_text="Now?",
            history=[("Before?", "Earlier answer")],
            model="m",
            evidence=[],
        )
    assert llm.calls[0][2] == [
        LlmMessage(role="user", content="Before?"),
        LlmMessage(role="assistant", content="Earlier answer"),
        LlmMessage(role="user", content="Now?"),
    ]


async def test_post_check_reads_two_probabilities_and_survives_a_failure():
    script = (
        Script()
        .post_check(contradicts=0.7, guilt=0.2)
        .fail("post_check", DeciderConnectionError("jev", "down"))
    )
    async with playing(script) as h:
        ok = await post_check(h.deps, reply="I was in the hall.", persona=PERSONA, evidence=[])
        bad = await post_check(h.deps, reply="I was in the hall.", persona=PERSONA, evidence=[])
    assert (ok.contradicts_says, ok.claims_guilt_or_blames_other, ok.failed) == (0.7, 0.2, False)
    assert (bad.contradicts_says, bad.failed) == (None, True)
    assert ok.decision_id and ok.decision_id != bad.decision_id


@pytest.mark.parametrize("preset", ["short", "standard", "long"])
def test_the_canned_line_passes_check_reply_for_many_seeds(preset):
    from gumshoe.mcp_server import GameHost
    from tests.mcp_server.helpers import SeqIds

    for seed in range(40):
        host = GameHost(ids=SeqIds())
        new = host.new_game(seed, preset)
        for suspect in new.brief.suspects:
            persona = host.persona_brief(new.game, suspect.handle)
            check = host.check_reply(new.game, suspect.handle, "Tell me.", canned_line(persona))
            assert check.ok, (seed, preset, suspect.name, check.violations)
