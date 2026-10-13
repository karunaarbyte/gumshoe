import pytest

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.events import (
    Clarify,
    Confirm,
    GameOver,
    IntentEvent,
    PostCheck,
    Reply,
    ToolCall,
    ToolResult,
)
from gumshoe.agent.game import ToolFailure
from gumshoe.agent.llm import LlmError
from gumshoe.agent.pending import Pending
from gumshoe.agent.turn import APOLOGY, HELP, UNREACHABLE
from gumshoe.cases import AccusationResult, SourceResult
from gumshoe.decider import DeciderAllFailedError, DeciderConnectionError
from tests.agent.fakes import Script, ScriptedLlm
from tests.agent.harness import playing, turn
from tests.mcp_server.helpers import castle_case, explore_all, true_triple


def kinds(events):
    return [e.kind for e in events]


def only(events, cls):
    [match] = [e for e in events if isinstance(e, cls)]
    return match


def place(h, i=0):
    return f"place_{h.brief.locations[i].number}"


def suspect(h, i=0):
    return f"suspect_{h.brief.suspects[i].number}"


async def test_a_search_calls_the_tool_and_ends_with_done():
    script = Script().understand(intent="search", target="place_1")
    async with playing(script) as h:
        events = await turn(h, "search the first place")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "done"]
    call = only(events, ToolCall)
    assert call.tool == "search" and call.args["location"] == h.brief.locations[0].handle
    result = only(events, ToolResult)
    assert result.ok and result.data["kind"] == "search"
    assert h.ctx.exchanges and h.ctx.exchanges[-1][0] == "search the first place"
    assert "searched" in h.ctx.exchanges[-1][1]


async def test_the_intent_event_carries_the_decision_id_the_decider_was_given():
    script = Script().understand(intent="notebook")
    async with playing(script) as h:
        events = await turn(h, "what do I know")
    intent = only(events, IntentEvent)
    assert h.decider.calls[0][0] == "understand" and h.decider.calls[0][2] == intent.decision_id
    assert only(events, ToolResult).tool == "notebook"


async def test_records_checks_a_suspect_or_place():
    script = Script().understand(intent="records", target="suspect_1")
    async with playing(script) as h:
        events = await turn(h, "pull the file on the first suspect")
    assert only(events, ToolCall).tool == "check_records"


@pytest.mark.parametrize("name", ["meta", "other"])
async def test_meta_and_other_get_the_help_line_and_call_no_tool(name):
    script = Script().understand(intent=name)
    async with playing(script) as h:
        events = await turn(h, "how do I play")
    assert kinds(events) == ["intent", "reply", "done"]
    reply = only(events, Reply)
    assert (reply.text, reply.source, reply.speaker) == (HELP, "help", None)


async def test_low_intent_confidence_asks_to_clarify_and_calls_nothing():
    script = Script().understand(intent="search", target="place_1", intent_p=0.4)
    async with playing(script) as h:
        events = await turn(h, "hmm")
    assert kinds(events) == ["intent", "clarify", "done"]
    assert only(events, Clarify).reason == "low_confidence"


@pytest.mark.parametrize(
    "kw",
    [{"target": "none"}, {"target": "place_1", "target_p": 0.3}],
    ids=["none", "unsure"],
)
async def test_a_missing_or_unsure_target_asks_which_one(kw):
    script = Script().understand(intent="search", **kw)
    async with playing(script) as h:
        events = await turn(h, "search there")
    assert only(events, Clarify).reason == "bad_target" and "tool_call" not in kinds(events)


async def test_a_notebook_request_needs_no_target():
    script = Script().understand(intent="notebook", target="none", target_p=0.1)
    async with playing(script) as h:
        events = await turn(h, "notes")
    assert "clarify" not in kinds(events) and only(events, ToolResult).tool == "notebook"


@pytest.mark.parametrize(
    ("intent", "target"),
    [("search", "suspect_1"), ("interrogate", "place_1"), ("talk", "place_1")],
)
async def test_a_target_of_the_wrong_kind_is_a_mismatch(intent, target):
    script = Script().understand(intent=intent, target=target)
    async with playing(script) as h:
        events = await turn(h, "x")
    assert only(events, Clarify).reason == "mismatch" and "tool_call" not in kinds(events)


async def test_interrogating_voices_the_suspect_and_runs_a_post_check():
    script = (
        Script()
        .understand(intent="interrogate", target="suspect_1", weight=1.0)
        .post_check(contradicts=0.3, guilt=0.4)
    )
    llm = ScriptedLlm(["I was in the hall."])
    async with playing(script, llm) as h:
        events = await turn(h, "where were you")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "reply", "post_check", "done"]
    reply = only(events, Reply)
    assert reply.text == "I was in the hall." and reply.source == "draft" and reply.check_ok
    assert reply.speaker == h.brief.suspects[0].name
    post = only(events, PostCheck)
    assert (post.contradicts_says, post.claims_guilt_or_blames_other) == (0.3, 0.4)
    assert llm.calls[0][0] == AgentConfig().model_default
    assert h.ctx.exchanges[-1] == ("where were you", "I was in the hall.")


async def test_a_dramatic_moment_uses_the_dramatic_model():
    script = Script().understand(intent="interrogate", target="suspect_1", weight=3.0).post_check()
    llm = ScriptedLlm(["Hmm."])
    async with playing(script, llm) as h:
        await turn(h, "confess!")
    assert llm.calls[0][0] == AgentConfig().model_dramatic


async def test_talking_voices_only_what_the_suspect_already_said_and_adds_no_facts():
    script = (
        Script()
        .understand(intent="interrogate", target="suspect_1")
        .post_check()
        .understand(intent="talk", target="suspect_1")
        .post_check()
    )
    llm = ScriptedLlm(["I was in the hall.", "As I said."])
    async with playing(script, llm) as h:
        await turn(h, "where were you")
        before = await h.deps.client.notebook(h.ctx.game)
        events = await turn(h, "anything else")
        after = await h.deps.client.notebook(h.ctx.game)
    assert "tool_call" not in kinds(events) and only(events, Reply).text == "As I said."
    assert before == after


async def test_a_locked_suspect_is_never_voiced():
    script = (
        Script()
        .understand(intent="talk", target="suspect_1")
        .understand(intent="interrogate", target="suspect_1")
    )
    llm = ScriptedLlm([])
    async with playing(script, llm, preset="long") as h:
        assert h.brief.suspects[0].locked
        talk = await turn(h, "talk to them")
        grill = await turn(h, "grill them")
    for events in (talk, grill):
        reply = only(events, Reply)
        assert (reply.text, reply.source) == (UNREACHABLE, "unreachable")
        assert "post_check" not in kinds(events)
    assert llm.calls == []
    assert only(grill, ToolResult).data["status"] == "locked"


async def test_a_leaking_draft_never_appears_in_any_event():
    case = castle_case(1)
    method = next(m.label for m in case.methods if m.id == case.truth.how)
    script = Script().understand(intent="interrogate", target="suspect_1").post_check()
    llm = ScriptedLlm([f"It was {method}!", "I was in the hall."])
    async with playing(script, llm) as h:
        events = await turn(h, "well?")
    assert only(events, Reply).text == "I was in the hall."
    assert method not in "".join(e.model_dump_json() for e in events)


async def test_an_unreachable_model_gives_the_canned_line_marked_degraded():
    script = Script().understand(intent="interrogate", target="suspect_1").post_check()
    llm = ScriptedLlm([LlmError("down")])
    async with playing(script, llm) as h:
        events = await turn(h, "well?")
    reply = only(events, Reply)
    assert reply.source == "canned" and reply.degraded is True
    assert reply.text.startswith(h.brief.suspects[0].name) and "looks away" in reply.text


async def test_a_failed_post_check_is_recorded_and_does_not_change_the_reply():
    script = (
        Script()
        .understand(intent="interrogate", target="suspect_1")
        .fail("post_check", DeciderConnectionError("jev", "down"))
    )
    llm = ScriptedLlm(["I was in the hall."])
    async with playing(script, llm) as h:
        events = await turn(h, "well?")
    assert only(events, Reply).text == "I was in the hall." and only(events, PostCheck).failed


@pytest.mark.parametrize(
    "error",
    [
        DeciderConnectionError("jev", "down"),
        DeciderAllFailedError({"jev": DeciderConnectionError("jev", "down")}),
    ],
    ids=["one", "all"],
)
async def test_a_failed_understand_is_the_apology_and_changes_nothing(error):
    script = Script().fail("understand", error)
    async with playing(script) as h:
        h.ctx.pending = Pending(kind="give_up", line="Give up?")
        events = await turn(h, "search")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["clarify", "done"]
    assert (only(events, Clarify).reason, only(events, Clarify).text) == ("error", APOLOGY)
    assert only(events, Clarify).decision_id == h.decider.calls[0][2]
    assert h.ctx.pending is not None and h.ctx.exchanges == []
    assert brief.status == "playing"


async def test_a_malformed_decision_is_the_apology_too():
    script = Script()
    script.queues["understand"].append(lambda q: {})
    async with playing(script) as h:
        events = await turn(h, "x")
    assert kinds(events) == ["clarify", "done"]


async def test_a_bug_in_a_stage_is_the_apology_and_the_turn_still_ends(monkeypatch, caplog):
    script = Script().understand(intent="notebook")
    async with playing(script) as h:

        async def boom(game):
            raise RuntimeError("secret skeleton detail f_deadbeef")

        monkeypatch.setattr(h.deps.client, "notebook", boom)
        events = await turn(h, "notes")
    assert kinds(events)[-2:] == ["clarify", "done"]
    assert "deadbeef" not in "".join(e.model_dump_json() for e in events)


async def test_an_unknown_game_ends_the_stream_quietly():
    script = Script()
    async with playing(script) as h:
        await h.deps.client.close_game(h.ctx.game)
        events = await turn(h, "search")
    assert kinds(events) == ["done"]


async def test_a_finished_game_costs_no_decision_and_yields_the_reveal():
    script = Script()
    async with playing(script) as h:
        await h.deps.client.give_up(h.ctx.game)
        events = await turn(h, "search again")
    assert kinds(events) == ["game_over", "done"]
    over = only(events, GameOver)
    assert over.outcome == "lost" and over.reveal.culprit
    assert h.decider.calls == []


# --- the confirm flows -------------------------------------------------------------------------


async def test_give_up_asks_first_and_only_a_yes_gives_up():
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.95)
    async with playing(script) as h:
        first = await turn(h, "I give up")
        assert kinds(first) == ["intent", "confirm", "done"]
        assert only(first, Confirm).pending == "give_up" and h.ctx.pending is not None
        brief = await h.deps.client.case_brief(h.ctx.game)
        assert brief.status == "playing"
        second = await turn(h, "yes")
    assert "Waiting for the player to confirm: Give up and see the answer?" in h.decider.calls[1][1]
    assert kinds(second) == ["intent", "tool_call", "tool_result", "game_over", "done"]
    over = only(second, GameOver)
    assert over.outcome == "gave_up" and over.reveal.culprit and h.ctx.pending is None


async def test_a_no_cancels_the_pending_action_and_the_game_goes_on():
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.05)
    async with playing(script) as h:
        await turn(h, "I give up")
        events = await turn(h, "no, wait")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["intent", "cancelled", "done"] and h.ctx.pending is None
    assert brief.status == "playing"


async def test_a_no_with_a_real_new_request_cancels_and_handles_it():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="search", target="place_1", confirm=0.05)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        events = await turn(h, "no, search the first place")
    assert kinds(events) == ["intent", "cancelled", "tool_call", "tool_result", "done"]


async def test_the_grey_band_asks_once_more_then_lets_it_go():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="other", confirm=0.5)
        .understand(intent="other", confirm=0.5)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        again = await turn(h, "hmm")
        assert only(again, Clarify).reason == "pending"
        assert h.ctx.pending is not None and h.ctx.pending.reasked
        last = await turn(h, "hmm?")
    assert only(last, Reply).source == "help" and h.ctx.pending is None


async def test_a_new_request_in_the_grey_band_drops_the_pending_action():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="search", target="place_1", confirm=0.5)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        events = await turn(h, "search the first place")
    assert "tool_call" in kinds(events) and h.ctx.pending is None


def names_of_truth(h, seed=1):
    case = castle_case(seed)
    who, how, why = true_triple(h.host, h.ctx.game, case)

    def name(axis, handle):
        return next(c.name for c in h.host.nameable(h.ctx.game, axis).options if c.handle == handle)

    return name("who", who), name("how", how), name("why", why)


async def test_a_true_accusation_is_confirmed_then_won_and_revealed():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse")
        h.script.parse(who=who, how=how, why=why)
        h.script.understand(intent="other", confirm=0.95)
        first = await turn(h, "it was them, with that, for this")
        assert kinds(first) == ["intent", "confirm", "done"]
        assert "Your accusation" in only(first, Confirm).text
        assert h.ctx.pending is not None and h.ctx.pending.kind == "accuse"
        second = await turn(h, "yes")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(second) == ["intent", "tool_call", "tool_result", "game_over", "done"]
    assert only(second, GameOver).outcome == "won" and brief.status == "won"
    assert [d[0] for d in h.decider.calls] == ["understand", "parse_accusation", "understand"]


async def test_yes_runs_the_accusation_exactly_once():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        other = next(c.name for c in h.host.nameable(h.ctx.game, "who").options if c.name != who)
        h.script.understand(intent="accuse").parse(who=other, how=how, why=why)
        h.script.understand(intent="other", confirm=0.95)
        h.script.understand(intent="other", confirm=0.95)  # a second yes, nothing pending now
        await turn(h, "accuse")
        first_yes = await turn(h, "yes")
        second_yes = await turn(h, "yes")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert only(first_yes, ToolCall).tool == "accuse"
    assert kinds(second_yes) == ["intent", "reply", "done"]  # the help line, no second accuse
    assert brief.attempts_left == 2


async def test_yes_together_with_a_new_accusation_never_spends_the_old_one():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        s = h.script
        s.understand(intent="accuse").parse(who=who, how=how, why=why)
        s.understand(intent="accuse", confirm=0.95)  # "yes, but ..."
        s.parse(who=None, how=None, why=None)
        await turn(h, "accuse")
        events = await turn(h, "yes, but actually the cook")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert brief.attempts_left == 3 and "game_over" not in kinds(events)
    assert only(events, Clarify).reason == "accusation"


async def test_an_unclear_accusation_names_what_is_missing_and_sets_nothing_pending():
    async with playing(Script()) as h:
        s = h.script
        s.understand(intent="accuse").parse(who=None)
        events = await turn(h, "I think someone did it")
    clarify = only(events, Clarify)
    assert clarify.reason == "accusation" and "how" in clarify.text
    assert h.ctx.pending is None


async def test_a_repeated_accusation_is_refused_before_confirming():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        # make a wrong accusation first by naming a different suspect for who
        other = next(c.name for c in h.host.nameable(h.ctx.game, "who").options if c.name != who)
        s = h.script
        s.understand(intent="accuse").parse(who=other, how=how, why=why)
        s.understand(intent="other", confirm=0.95)
        s.understand(intent="accuse").parse(who=other, how=how, why=why)
        await turn(h, "accuse the other one")
        miss = await turn(h, "yes")
        assert only(miss, ToolResult).data["correct"] == 2 and "game_over" not in kinds(miss)
        again = await turn(h, "accuse the other one again")
    clarify = only(again, Clarify)
    assert clarify.reason == "accusation" and "already" in clarify.text


async def test_a_failed_parse_decision_is_the_apology_and_sets_nothing_pending():
    async with playing(Script()) as h:
        s = h.script
        s.understand(intent="accuse").fail(
            "parse_accusation", DeciderConnectionError("jev", "down")
        )
        events = await turn(h, "accuse")
    assert only(events, Clarify).text == APOLOGY and h.ctx.pending is None


async def test_the_whole_script_is_consumed():
    script = Script().understand(intent="notebook")
    async with playing(script) as h:
        await turn(h, "notes")
    assert script.left() == {}


async def test_a_suspect_hears_only_their_own_conversation():
    script = (
        Script()
        .understand(intent="search", target="place_1")
        .understand(intent="interrogate", target="suspect_1")
        .post_check()
        .understand(intent="interrogate", target="suspect_2")
        .post_check()
    )
    llm = ScriptedLlm(["I was in the hall.", "Hmm."])
    async with playing(script, llm) as h:
        await turn(h, "search the first place")
        await turn(h, "where were you")
        await turn(h, "and you?")
    assert [m.content for m in llm.calls[0][2]] == ["where were you"]
    assert [m.content for m in llm.calls[1][2]] == ["and you?"]


# --- failure rows ------------------------------------------------------------------------------


def failing(code, message="nope"):
    async def boom(*args, **kwargs):
        raise ToolFailure(code, message)

    return boom


async def test_a_refused_search_is_a_failed_tool_result_and_memory_does_not_claim_success(
    monkeypatch,
):
    script = Script().understand(intent="search", target="place_1")
    async with playing(script) as h:
        monkeypatch.setattr(h.deps.client, "search", failing("unknown_handle", "no such place"))
        events = await turn(h, "search the first place")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "done"]
    result = only(events, ToolResult)
    assert (result.ok, result.code) == (False, "unknown_handle")
    assert h.ctx.exchanges == [("search the first place", "could not search there")]


async def test_a_server_bug_in_a_tool_is_the_apology(monkeypatch):
    script = Script().understand(intent="search", target="place_1")
    async with playing(script) as h:
        monkeypatch.setattr(h.deps.client, "search", failing("internal", "the game server failed"))
        events = await turn(h, "search the first place")
    assert kinds(events) == ["intent", "tool_call", "clarify", "done"]
    assert only(events, Clarify).reason == "error"


async def test_a_bad_parse_argument_is_the_apology_with_the_parse_decision(monkeypatch):
    script = Script().understand(intent="accuse").parse(who=None)
    async with playing(script) as h:
        monkeypatch.setattr(h.deps.client, "interpret_accusation", failing("bad_argument"))
        events = await turn(h, "accuse someone")
    assert kinds(events) == ["intent", "clarify", "done"]
    clarify = only(events, Clarify)
    assert (clarify.reason, clarify.text) == ("error", APOLOGY)
    assert clarify.decision_id == h.decider.calls[1][2] and h.ctx.pending is None


async def test_a_not_permitted_accusation_clears_the_pending_one_and_spends_nothing(monkeypatch):
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse").parse(who=who, how=how, why=why)
        h.script.understand(intent="other", confirm=0.95)
        await turn(h, "accuse")

        async def refused(*args, **kwargs):
            return AccusationResult(
                status="not_permitted",
                correct=None,
                attempts_left=3,
                game="playing",
                message="You cannot accuse yet.",
            )

        monkeypatch.setattr(h.deps.client, "accuse", refused)
        events = await turn(h, "yes")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["intent", "tool_call", "tool_result", "clarify", "done"]
    clarify = only(events, Clarify)
    assert (clarify.reason, clarify.text) == ("accusation", "You cannot accuse yet.")
    assert h.ctx.pending is None and brief.attempts_left == 3


async def test_a_give_up_refused_with_game_over_is_a_failed_result_and_no_game_over(monkeypatch):
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.95)
    async with playing(script) as h:
        await turn(h, "I give up")
        monkeypatch.setattr(h.deps.client, "give_up", failing("game_over", "it is over"))
        events = await turn(h, "yes")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "done"]
    assert only(events, ToolResult).ok is False and h.ctx.pending is None
    assert h.ctx.exchanges[-1][1] == "could not give up"


async def test_a_later_stage_failing_keeps_the_tool_result_and_remembers_the_exchange(monkeypatch):
    script = Script().understand(intent="interrogate", target="suspect_1")
    llm = ScriptedLlm(["I was in the hall."])
    async with playing(script, llm) as h:
        monkeypatch.setattr(h.deps.client, "check_reply", failing("internal"))
        events = await turn(h, "where were you")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "clarify", "done"]
    assert only(events, ToolResult).ok and only(events, Clarify).text == APOLOGY
    [(said, summary)] = h.ctx.exchanges
    assert said == "where were you" and summary.startswith("questioned ") and "new facts" in summary


async def test_naming_a_suspect_the_gate_has_not_opened_says_so():
    async with playing(Script(), preset="long") as h:
        locked = h.brief.suspects[0]
        assert locked.locked
        h.script.understand(intent="accuse").parse(who=locked.name)
        events = await turn(h, f"it was {locked.name}")
    clarify = only(events, Clarify)
    assert clarify.reason == "accusation" and "cannot name the who yet" in clarify.text
    assert h.ctx.pending is None


async def test_an_unknown_interrogation_is_unreachable_and_calls_no_llm(monkeypatch):
    script = Script().understand(intent="interrogate", target="suspect_1")
    llm = ScriptedLlm([])
    async with playing(script, llm) as h:

        async def unknown(*args, **kwargs):
            return SourceResult(kind="interrogate", label="them", status="unknown")

        monkeypatch.setattr(h.deps.client, "interrogate", unknown)
        events = await turn(h, "grill them")
    assert only(events, Reply).source == "unreachable" and llm.calls == []
    assert "post_check" not in kinds(events)


async def test_a_new_request_in_the_grey_band_drops_a_pending_accusation():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse").parse(who=who, how=how, why=why)
        h.script.understand(intent="search", target="place_1", confirm=0.5)
        await turn(h, "accuse")
        assert h.ctx.pending is not None
        events = await turn(h, "hmm, search the first place")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert "tool_call" in kinds(events) and h.ctx.pending is None and brief.attempts_left == 3


async def test_a_confirmed_give_up_next_to_a_pending_accusation_is_not_a_yes():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse").parse(who=who, how=how, why=why)
        h.script.understand(intent="give_up", confirm=0.95)
        await turn(h, "accuse")
        events = await turn(h, "yes, I give up")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert brief.status == "playing" and brief.attempts_left == 3
    assert kinds(events) == ["intent", "confirm", "done"]  # asks about giving up instead
    assert h.ctx.pending is not None and h.ctx.pending.kind == "give_up"


async def test_a_cancel_with_a_new_request_is_one_exchange():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="search", target="place_1", confirm=0.05)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        await turn(h, "no, search the first place")
    assert len(h.ctx.exchanges) == 2
    said, summary = h.ctx.exchanges[-1]
    assert said == "no, search the first place"
    assert summary.startswith("cancelled, then searched ")
