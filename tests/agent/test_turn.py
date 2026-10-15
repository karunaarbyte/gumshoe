import asyncio
import logging
from dataclasses import replace

import pytest

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.events import (
    Clarify,
    Confirm,
    Done,
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
from gumshoe.agent.turn import (
    APOLOGY,
    HELP,
    NOTHING_PENDING,
    UNREACHABLE,
)
from gumshoe.cases import AccusationResult, SourceResult
from gumshoe.decider import (
    DeciderAllFailedError,
    DeciderAPIError,
    DeciderConnectionError,
    describe_failure,
)
from tests.agent.fakes import Script, ScriptedDecider, ScriptedLlm
from tests.agent.harness import answer, playing, press, turn
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
    assert reply.text == "I was in the hall." and reply.source == "draft"
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


def assert_logged_class_only(caplog, name, *secrets):
    """Every record is free of a traceback and of the exception's text; one names its class."""
    assert caplog.records
    assert all(r.exc_info is None and r.exc_text is None for r in caplog.records)
    for secret in secrets:
        assert secret not in caplog.text
    assert name in caplog.text


async def test_a_crashing_stage_logs_its_class_never_its_text_or_traceback(monkeypatch, caplog):
    script = Script().understand(intent="notebook")
    async with playing(script) as h:

        async def boom(game):
            raise RuntimeError("secret player text sk-xyz")

        monkeypatch.setattr(h.deps.client, "notebook", boom)
        with caplog.at_level(logging.DEBUG):
            await turn(h, "notes")
    assert_logged_class_only(caplog, "RuntimeError", "sk-xyz", "secret player text", "Traceback")


async def test_a_refused_game_call_logs_its_code_never_its_message(monkeypatch, caplog):
    script = Script().understand(intent="notebook")
    async with playing(script) as h:
        monkeypatch.setattr(h.deps.client, "notebook", failing("internal", "secret sk-xyz"))
        with caplog.at_level(logging.DEBUG):
            await turn(h, "notes")
    assert_logged_class_only(caplog, "ToolFailure", "sk-xyz")


async def test_a_turn_timeout_that_is_not_the_budget_logs_the_class_only(monkeypatch, caplog):
    script = Script().understand(intent="notebook")
    async with playing(script) as h:

        async def boom(game):
            raise TimeoutError("secret sk-xyz")

        monkeypatch.setattr(h.deps.client, "notebook", boom)
        with caplog.at_level(logging.DEBUG):
            await turn(h, "notes")
    assert_logged_class_only(caplog, "TimeoutError", "sk-xyz")


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
        second = await answer(h, "yes")
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
        second = await answer(h, "yes")
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
        first_yes = await answer(h, "yes")
        second_yes = await answer(h, "yes")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert only(first_yes, ToolCall).tool == "accuse"
    assert kinds(second_yes) == ["intent", "reply", "done"]  # no second accuse
    assert only(second_yes, Reply).text.startswith(NOTHING_PENDING)
    assert brief.attempts_left == 2


async def test_yes_together_with_a_different_accusation_never_spends_the_old_one():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        other = next(c.name for c in h.host.nameable(h.ctx.game, "who").options if c.name != who)
        s = h.script
        s.understand(intent="accuse").parse(who=who, how=how, why=why)
        s.understand(intent="accuse", confirm=0.95)  # "yes, but ..."
        s.parse(who=other, how=how, why=why)
        await turn(h, "accuse")
        old_id = h.ctx.pending.id if h.ctx.pending else None
        events = await answer(h, "yes, but actually the other one")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert brief.attempts_left == 3 and "game_over" not in kinds(events)
    assert kinds(events) == ["intent", "cancelled", "confirm", "done"]
    assert h.ctx.pending is not None and h.ctx.pending.id != old_id
    assert only(events, Confirm).pending_id == h.ctx.pending.id


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
        miss = await answer(h, "yes")
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
        events = await answer(h, "yes")
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
        events = await answer(h, "yes")
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
    # the accusation is dropped (and says so), then it asks about giving up instead
    assert kinds(events) == ["intent", "cancelled", "confirm", "done"]
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


# --- telemetry and logging ---------------------------------------------------------------------


async def test_the_reply_carries_the_model_its_drafts_and_latency_and_done_the_turn_time():
    script = Script().understand(intent="interrogate", target="suspect_1").post_check()
    llm = ScriptedLlm(["I was in the hall."])
    async with playing(script, llm) as h:
        events = await turn(h, "where were you")
    reply = only(events, Reply)
    assert (reply.model, reply.drafts) == (AgentConfig().model_default, 1)
    assert reply.latency_ms is not None and reply.latency_ms >= 0
    done = events[-1]
    assert isinstance(done, Done) and done.turn_ms is not None and done.turn_ms >= 0


async def test_a_failed_understand_is_logged_by_class_and_backend_never_the_players_text(caplog):
    error = DeciderAPIError("jev", 500, "echo: my private words")
    script = Script().fail("understand", error)
    async with playing(script) as h:
        with caplog.at_level(logging.WARNING, logger="gumshoe.agent.turn"):
            await turn(h, "my private words")
    assert "DeciderAPIError (jev, HTTP 500)" in caplog.text
    assert "private" not in caplog.text


def test_a_total_failure_is_described_backend_by_backend():
    error = DeciderAllFailedError(
        {
            "jev": DeciderConnectionError("jev", "down"),
            "nimble": DeciderAPIError("nimble", 502, "body"),
        }
    )
    assert describe_failure(error) == (
        "DeciderAllFailedError (jev: DeciderConnectionError, nimble: DeciderAPIError)"
    )


# --- dropped confirmations and the end state ---------------------------------------------------


async def test_a_new_request_that_drops_the_pending_action_says_cancelled_first():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="search", target="place_1", confirm=0.5)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        events = await turn(h, "search the first place")
    assert kinds(events) == ["intent", "cancelled", "tool_call", "tool_result", "done"]
    assert h.ctx.pending is None


async def test_letting_the_pending_action_go_after_the_reask_says_cancelled():
    script = (
        Script()
        .understand(intent="give_up")
        .understand(intent="other", confirm=0.5)
        .understand(intent="other", confirm=0.5)
    )
    async with playing(script) as h:
        await turn(h, "I give up")
        await turn(h, "hmm")
        last = await turn(h, "hmm?")
    assert kinds(last) == ["intent", "cancelled", "reply", "done"]


async def test_a_given_up_game_stays_given_up_on_later_turns():
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.95)
    async with playing(script) as h:
        await turn(h, "I give up")
        await answer(h, "yes")
        later = await turn(h, "search again")
    assert kinds(later) == ["game_over", "done"]
    assert only(later, GameOver).outcome == "gave_up" and h.ctx.outcome == "gave_up"


# --- a yes answers one confirmation ------------------------------------------------------------


async def test_the_confirm_event_carries_the_id_of_the_pending_action():
    script = Script().understand(intent="give_up")
    async with playing(script) as h:
        events = await turn(h, "I give up")
    assert h.ctx.pending is not None and only(events, Confirm).pending_id == h.ctx.pending.id


@pytest.mark.parametrize("sent", [None, "0" * 32], ids=["no id", "stale id"])
async def test_a_yes_without_the_confirmations_id_shows_it_again_and_spends_nothing(sent):
    script = Script().understand(intent="give_up").understand(intent="other", confirm=0.95)
    async with playing(script) as h:
        first = only(await turn(h, "I give up"), Confirm)
        events = await turn(h, "yes", pending_id=sent)
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["intent", "confirm", "done"]
    assert only(events, Confirm) == first  # the same confirmation, the same id
    assert brief.status == "playing" and h.ctx.pending is not None
    assert h.ctx.pending.id == first.pending_id


async def test_a_reshown_accusation_keeps_its_warnings():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        warned = next(c for c in h.host.nameable(h.ctx.game, "who").options if c.warned)
        h.script.understand(intent="accuse").parse(who=warned.name, how=how, why=why)
        h.script.understand(intent="other", confirm=0.95)
        first = only(await turn(h, "accuse"), Confirm)
        again = only(await turn(h, "yes"), Confirm)
    assert first.warnings and again.warnings == first.warnings and again.text == first.text


@pytest.mark.parametrize("named", ["nothing", "the same suspect"])
async def test_yes_with_an_accusation_naming_nothing_new_is_the_yes(named):
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        s = h.script
        s.understand(intent="accuse").parse(who=who, how=how, why=why)
        s.understand(intent="accuse", confirm=0.95)  # "yes, accuse him"
        s.parse(who=None if named == "nothing" else who, how=None, why=None)
        await turn(h, "accuse")
        events = await answer(h, "yes, accuse him")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "game_over", "done"]
    assert only(events, GameOver).outcome == "won"
    assert [d[0] for d in h.decider.calls] == [
        "understand",
        "parse_accusation",
        "understand",
        "parse_accusation",
    ]


async def test_yes_with_an_accusation_still_needs_the_confirmations_id():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        s = h.script
        s.understand(intent="accuse").parse(who=who, how=how, why=why)
        s.understand(intent="accuse", confirm=0.95).parse(who=None, how=None, why=None)
        await turn(h, "accuse")
        events = await turn(h, "yes, accuse him")  # no id
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["intent", "confirm", "done"] and brief.attempts_left == 3


async def test_a_failed_reparse_leaves_the_pending_accusation_alone():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        s = h.script
        s.understand(intent="accuse").parse(who=who, how=how, why=why)
        s.understand(intent="accuse", confirm=0.95)
        s.fail("parse_accusation", DeciderConnectionError("jev", "down"))
        await turn(h, "accuse")
        kept = h.ctx.pending
        events = await answer(h, "yes, accuse him")
    assert kinds(events) == ["intent", "clarify", "done"]
    assert only(events, Clarify).text == APOLOGY and h.ctx.pending is kept


# --- the confirm button ------------------------------------------------------------------------


async def test_the_confirm_button_gives_up_without_asking_the_decider():
    script = Script().understand(intent="give_up")
    async with playing(script) as h:
        confirm = only(await turn(h, "I give up"), Confirm)
        events = await press(h, confirm.pending_id, "yes")
    assert kinds(events) == ["tool_call", "tool_result", "game_over", "done"]
    assert only(events, GameOver).outcome == "gave_up" and h.ctx.pending is None
    assert [c[0] for c in h.decider.calls] == ["understand"]  # only the first turn's
    assert h.ctx.exchanges[-1] == ("yes", "gave up")


async def test_the_confirm_button_wins_with_the_stored_accusation():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse").parse(who=who, how=how, why=why)
        confirm = only(await turn(h, "accuse"), Confirm)
        events = await press(h, confirm.pending_id, "yes")
    assert only(events, GameOver).outcome == "won"
    assert only(events, ToolCall).args["confirmed"] is True


async def test_the_cancel_button_cancels_and_the_game_goes_on():
    script = Script().understand(intent="give_up")
    async with playing(script) as h:
        confirm = only(await turn(h, "I give up"), Confirm)
        events = await press(h, confirm.pending_id, "no")
        brief = await h.deps.client.case_brief(h.ctx.game)
    assert kinds(events) == ["cancelled", "done"] and h.ctx.pending is None
    assert brief.status == "playing" and h.ctx.exchanges[-1] == ("no", "cancelled")


@pytest.mark.parametrize("answer", ["yes", "no"])
async def test_a_button_for_another_confirmation_does_nothing(answer):
    script = Script().understand(intent="give_up")
    async with playing(script) as h:
        await turn(h, "I give up")
        kept = h.ctx.pending
        events = await press(h, "0" * 32, answer)
    assert kinds(events) == ["clarify", "done"]
    assert only(events, Clarify).reason == "pending" and h.ctx.pending is kept


# --- copy and the structured accusation clarify ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "intent_p", "pending_id"),
    [("Yes!", 0.9, None), ("  OK  ", 0.3, None), ("sure, go on", 0.9, "0" * 32)],
    ids=["bare yes", "unsure ok", "stale id"],
)
async def test_a_yes_with_nothing_pending_says_there_is_nothing_to_confirm(
    text, intent_p, pending_id
):
    script = Script().understand(intent="other", intent_p=intent_p)
    async with playing(script) as h:
        events = await turn(h, text, pending_id=pending_id)
    assert kinds(events) == ["intent", "reply", "done"]
    assert only(events, Reply).text == f"{NOTHING_PENDING} {HELP}"


async def test_an_ordinary_question_still_gets_the_plain_help_line():
    script = Script().understand(intent="other")
    async with playing(script) as h:
        events = await turn(h, "yes or no, who knows")
    assert only(events, Reply).text == HELP


async def test_an_unclear_accusation_lists_each_problem_with_the_names_that_may_be_used():
    async with playing(Script()) as h:
        explore_all(h.host, h.ctx.game)
        who, how, why = names_of_truth(h)
        h.script.understand(intent="accuse").parse(who=None, how=how, why=why)
        events = await turn(h, "it was someone, with that, for this")
    [problem] = only(events, Clarify).problems
    nameable = h.host.nameable(h.ctx.game, "who").options
    assert (problem.axis, problem.reason) == ("who", "unclear")
    assert [(o.handle, o.name) for o in problem.options] == [(c.handle, c.name) for c in nameable]


async def test_other_clarifies_carry_no_problems():
    script = Script().understand(intent="search", target="none")
    async with playing(script) as h:
        events = await turn(h, "search")
    assert only(events, Clarify).problems == ()


# --- the turn budget ---------------------------------------------------------------------------


class SlowLlm(ScriptedLlm):
    async def complete(self, model, system, messages):
        self.calls.append((model, system, list(messages)))
        await asyncio.sleep(5)
        return "too late"


class SlowDecider(ScriptedDecider):
    async def decide(self, state, questions, *, node="adhoc", decision_id=None):
        if node == "understand":
            await asyncio.sleep(5)
        return await super().decide(state, questions, node=node, decision_id=decision_id)


async def test_a_persona_model_slower_than_its_budget_gives_the_canned_line():
    script = Script().understand(intent="interrogate", target="suspect_1").post_check()
    llm = SlowLlm([])
    async with playing(script, llm, config=AgentConfig(turn_timeout_s=2.4)) as h:
        async with asyncio.timeout(5):
            events = await turn(h, "where were you")
    reply = only(events, Reply)
    assert (reply.source, reply.degraded, reply.drafts) == ("canned", True, 1)
    assert kinds(events)[-2:] == ["post_check", "done"]  # the turn itself went on


async def test_a_turn_that_outlives_its_budget_ends_with_the_apology_and_done():
    script = Script().understand(intent="notebook")
    async with playing(script, config=AgentConfig(turn_timeout_s=0.2)) as h:
        h.deps = replace(h.deps, decider=SlowDecider(script))
        h.ctx.pending = kept = Pending(kind="give_up", line="Give up?")
        async with asyncio.timeout(3):
            events = await turn(h, "notes")
    assert kinds(events) == ["clarify", "done"]
    assert only(events, Clarify).text == APOLOGY and h.ctx.pending is kept
