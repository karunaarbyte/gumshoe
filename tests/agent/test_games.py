from dataclasses import replace

from gumshoe.agent.events import Clarify, Confirm, GameOver, IntentEvent, PostCheck, ToolResult
from gumshoe.decider import ShadowDecider
from tests.agent.fakes import Script, ScriptedLlm
from tests.agent.harness import playing, turn
from tests.agent.test_turn import names_of_truth, only
from tests.decider.fakes import FakeRecorder
from tests.mcp_server.helpers import castle_case


async def explore_by_turns(h, script, llm_replies):
    """Search every place and question every suspect through free-text turns, twice over."""
    for _ in range(2):
        for loc in h.brief.locations:
            script.understand(intent="search", target=f"place_{loc.number}")
            await turn(h, f"search {loc.name}")
        for sus in h.brief.suspects:
            script.understand(intent="interrogate", target=f"suspect_{sus.number}").post_check()
            await turn(h, f"question {sus.name}")


async def test_a_game_won_from_free_text_turns_only():
    script = Script()
    llm = ScriptedLlm(["I was somewhere else."] * 40)
    async with playing(script, llm, seed=3) as h:
        await explore_by_turns(h, script, llm)
        who, how, why = names_of_truth(h, seed=3)
        script.understand(intent="accuse").parse(who=who, how=how, why=why)
        script.understand(intent="other", confirm=0.95)
        first = await turn(h, "I accuse them")
        second = await turn(h, "yes")
    assert only(first, Confirm).pending == "accuse"
    over = only(second, GameOver)
    case = castle_case(3)
    assert over.outcome == "won"
    assert over.reveal.culprit == next(
        s.display_name for s in case.suspects if s.id == case.truth.who
    )
    assert script.left() == {}


async def test_a_game_lost_after_three_wrong_accusations():
    script = Script()
    llm = ScriptedLlm(["Nothing to say."] * 40)
    async with playing(script, llm, seed=3) as h:
        await explore_by_turns(h, script, llm)
        who, how, why = names_of_truth(h, seed=3)
        wrongs = [c.name for c in h.host.nameable(h.ctx.game, "who").options if c.name != who][:3]
        outcome = None
        for wrong in wrongs:
            script.understand(intent="accuse").parse(who=wrong, how=how, why=why)
            script.understand(intent="other", confirm=0.95)
            await turn(h, f"it was {wrong}")
            events = await turn(h, "yes")
            result = only(events, ToolResult)
            assert result.ok and result.data["correct"] == 2
            overs = [e for e in events if isinstance(e, GameOver)]
            outcome = overs[0].outcome if overs else None
    assert outcome == "lost"


async def test_every_call_to_the_decider_carries_a_decision_id():
    script = Script().understand(intent="interrogate", target="suspect_1").post_check()
    llm = ScriptedLlm(["Hmm."])
    async with playing(script, llm) as h:
        await turn(h, "well?")
    ids = [call[2] for call in h.decider.calls]
    assert len(ids) == 2 and all(ids) and ids[0] != ids[1]


async def test_every_decision_lands_in_the_log_under_its_node_and_joins_its_event():
    script = (
        Script()
        .understand(intent="interrogate", target="suspect_1")
        .post_check()
        .understand(intent="accuse")
        .parse(who=None, how=None, why=None)
    )
    recorder = FakeRecorder()
    async with playing(script, ScriptedLlm(["Hmm."])) as h:
        shadow = ShadowDecider(h.decider, None, recorder)
        h.deps = replace(h.deps, decider=shadow)
        talk = await turn(h, "well?")
        accuse = await turn(h, "someone did it")
        await shadow.drain()
    rows = {r.decision_id: r.node for batch in recorder.batches for r in batch}
    assert sorted(rows.values()) == ["parse_accusation", "post_check", "understand", "understand"]
    assert rows[only(talk, IntentEvent).decision_id] == "understand"
    assert rows[only(talk, PostCheck).decision_id] == "post_check"
    assert rows[only(accuse, IntentEvent).decision_id] == "understand"
    assert rows[only(accuse, Clarify).decision_id or ""] == "parse_accusation"
