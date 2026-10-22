import asyncio
import logging
from dataclasses import replace
from datetime import datetime
from typing import Literal

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.agent.events import Confirm
from gumshoe.api.errors import ApiError
from gumshoe.api.service import SHUTTING_DOWN, AgentService, SaveSummary
from gumshoe.mcp_server import GameError
from tests.agent.fakes import Script
from tests.api.helpers import OWNER, GatedDecider, HeldSave, idle, serving


def kinds(events):
    return [e.kind for e in events]


async def collect(service: AgentService, game: str, text: str):
    async with asyncio.timeout(10):  # a regression fails the test instead of hanging the suite
        return [event async for event in service.start_turn(game, text, owner=OWNER)]


async def test_a_turn_streams_the_agents_events_and_ends_with_done():
    script = Script().understand(intent="search", target="place_1")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        events = await collect(s.service, new.game, "search the first place")
    assert kinds(events) == ["intent", "tool_call", "tool_result", "done"]
    assert script.left() == {}


async def test_state_returns_the_brief_and_the_notebook():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        state = await s.service.state(new.game, owner=OWNER)
    assert state.brief == new.brief and state.notebook.sections is not None


async def test_an_unknown_game_fails_at_once_not_in_the_stream():
    async with serving(Script()) as s:
        with pytest.raises(ToolFailure) as caught:
            s.service.start_turn("nope", "hello", owner=OWNER)
        assert caught.value.code == "unknown_game"
        with pytest.raises(ToolFailure):
            await s.service.state("nope", owner=OWNER)
        with pytest.raises(ToolFailure):
            await s.service.delete_game("nope", owner=OWNER)
        with pytest.raises(ToolFailure):
            await s.service.save_game("nope", owner=OWNER)


async def test_chat_memory_lives_across_turns():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        await collect(s.service, new.game, "search the first place")
        await collect(s.service, new.game, "show my notebook")
    second_state = s.decider.calls[1][1]
    assert "Earlier the player said: search the first place" in second_state


async def test_two_games_keep_separate_memory():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    async with serving(script) as s:
        a = await s.service.new_game(1, owner=OWNER)
        b = await s.service.new_game(2, owner=OWNER)
        await collect(s.service, a.game, "search the first place")
        await collect(s.service, b.game, "show my notebook")
    assert "Earlier the player said" not in s.decider.calls[1][1]


async def test_a_second_turn_while_one_runs_is_refused_and_never_billed():
    script = Script().understand(intent="notebook").understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1, owner=OWNER)
        first = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        with pytest.raises(ApiError) as caught:
            s.service.start_turn(new.game, "two", owner=OWNER)
        assert (caught.value.status, caught.value.code) == (409, "turn_in_progress")
        gated.release.set()
        one = await first
        again = await collect(s.service, new.game, "three")  # free again once it ended
    assert kinds(one)[-1] == kinds(again)[-1] == "done"
    assert [c[1].splitlines()[0] for c in gated.calls] == [
        "Player says: one",
        "Player says: three",
    ]


async def test_the_game_is_free_again_when_a_turn_crashed():
    script = Script()  # empty: the turn dies with ScriptExhausted
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        assert await collect(s.service, new.game, "hello") == []
        script.understand(intent="notebook")
        again = await collect(s.service, new.game, "notes")  # not refused with 409
    assert kinds(again)[-1] == "done"


async def test_a_disconnect_does_not_stop_the_turn():
    script = Script().understand(intent="search", target="place_1").understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1, owner=OWNER)
        stream = s.service.start_turn(new.game, "search the first place", owner=OWNER)
        reader = asyncio.create_task(anext(stream))  # the client reads, then drops
        await gated.entered.wait()
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await stream.aclose()
        gated.release.set()
        await idle(s.service)
        await collect(s.service, new.game, "show my notebook")
    assert "Earlier the player said: search the first place" in gated.calls[1][1]


async def test_delete_closes_the_game_and_forgets_it():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        await s.service.delete_game(new.game, owner=OWNER)
        with pytest.raises(ToolFailure) as caught:
            s.service.start_turn(new.game, "hello", owner=OWNER)
        assert caught.value.code == "unknown_game"
        with pytest.raises(GameError):
            s.host.case_brief(new.game)  # the host raises its own error, not the client's


async def test_delete_waits_for_a_running_turn():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1, owner=OWNER)
        running = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        deleting = asyncio.create_task(s.service.delete_game(new.game, owner=OWNER))
        await asyncio.sleep(0.05)
        assert not deleting.done()
        gated.release.set()
        one, _ = await asyncio.gather(running, deleting)
    assert kinds(one)[-1] == "done" and len(one) > 1
    assert gated.started == 1


async def test_a_turn_waiting_behind_a_save_sees_the_game_deleted_and_does_nothing(
    monkeypatch, tmp_path
):
    async with serving(Script(), saves_dir=tmp_path) as s:
        new = await s.service.new_game(1, owner=OWNER)
        held = HeldSave(monkeypatch, s.service)
        saving = asyncio.create_task(s.service.save_game(new.game, owner=OWNER))
        await held.entered.wait()  # the save holds the lock
        deleting = asyncio.create_task(s.service.delete_game(new.game, owner=OWNER))
        await asyncio.sleep(0)  # the delete queues for the lock first
        waiting = asyncio.create_task(collect(s.service, new.game, "two"))
        await asyncio.sleep(0.05)
        held.release.set()
        _, _, two = await asyncio.gather(saving, deleting, waiting)
    assert kinds(two) == ["done"]  # saw the game gone, ran nothing
    assert s.decider.calls == []


async def test_a_turn_that_crashes_still_ends_the_stream():
    script = Script()  # empty: ScriptExhausted is a BaseException and escapes take_turn
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        events = await collect(s.service, new.game, "hello")
        await asyncio.wait_for(idle(s.service), timeout=5.0)
        assert events == []  # the stream ended instead of hanging
        script.understand(intent="notebook")  # the service still works: a second turn runs
        again = await collect(s.service, new.game, "show my notebook")
    assert kinds(again)[-1] == "done" and "tool_result" in kinds(again)


async def test_a_dead_turn_task_logs_its_class_never_a_traceback(caplog):
    script = Script()  # empty: ScriptExhausted escapes take_turn and kills the task
    with caplog.at_level(logging.DEBUG):
        async with serving(script) as s:
            new = await s.service.new_game(1, owner=OWNER)
            await collect(s.service, new.game, "secret player text sk-xyz")
            await asyncio.wait_for(idle(s.service), timeout=5.0)
    assert caplog.records
    assert all(r.exc_info is None and r.exc_text is None for r in caplog.records)
    assert "sk-xyz" not in caplog.text and "Traceback" not in caplog.text
    assert "ScriptExhausted" in caplog.text


async def test_save_and_load_register_the_loaded_game(tmp_path):
    script = Script().understand(intent="notebook")
    async with serving(script, saves_dir=tmp_path) as s:
        new = await s.service.new_game(1, owner=OWNER)
        saved = await s.service.save_game(new.game, owner=OWNER)
        loaded = await s.service.load_game(saved.name, owner=OWNER)
        assert loaded.game != new.game
        events = await collect(s.service, loaded.game, "show my notebook")
    assert kinds(events)[-1] == "done"


async def test_save_waits_for_a_running_turn(tmp_path):
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated, saves_dir=tmp_path) as s:
        new = await s.service.new_game(1, owner=OWNER)
        running = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        saving = asyncio.create_task(s.service.save_game(new.game, owner=OWNER))
        await asyncio.sleep(0.05)
        assert not saving.done()  # a save is taken between turns, never mid-turn
        gated.release.set()
        await running
        saved = await saving
    assert len(saved.name) == 16


async def test_aclose_cancels_a_running_turn_without_hanging():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated, grace_s=2.0) as s:
        new = await s.service.new_game(1, owner=OWNER)
        task = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        await asyncio.wait_for(s.service.aclose(), timeout=3.0)
        events = await asyncio.wait_for(task, timeout=1.0)  # ended: the turn was cancelled
    assert kinds(events) == ["clarify", "done"]  # said so, unlike a dropped connection
    assert events[0].reason == "error" and events[0].text == SHUTTING_DOWN


async def test_ten_games_run_turns_at_once():
    script = Script()
    for _ in range(10):
        script.understand(intent="notebook")
    async with serving(script) as s:
        games = [(await s.service.new_game(i, owner=OWNER)).game for i in range(1, 11)]
        results = await asyncio.gather(*(collect(s.service, g, "show my notebook") for g in games))
    assert all(kinds(r)[-1] == "done" and "tool_result" in kinds(r) for r in results)


async def test_a_turn_whose_reader_left_while_it_waited_does_not_run(monkeypatch, tmp_path):
    async with serving(Script(), saves_dir=tmp_path) as s:
        new = await s.service.new_game(1, owner=OWNER)
        held = HeldSave(monkeypatch, s.service)
        saving = asyncio.create_task(s.service.save_game(new.game, owner=OWNER))
        await held.entered.wait()  # the save holds the lock
        stream = s.service.start_turn(new.game, "two", owner=OWNER)
        reader = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)  # let the reader start waiting
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await stream.aclose()  # the client is gone
        held.release.set()
        await saving
        await idle(s.service)
    assert s.decider.calls == []  # the abandoned turn never reached the decider


def fail_close_once(monkeypatch, client, code: str) -> None:
    """Make the client's next close_game fail with `code`; later calls reach the host."""
    real_close = client.close_game
    failures = [code]

    async def close_game(game):
        if failures:
            raise ToolFailure(failures.pop(), "boom")
        return await real_close(game)

    monkeypatch.setattr(client, "close_game", close_game)


async def test_a_failed_close_keeps_the_game_so_delete_can_be_retried(monkeypatch):
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        fail_close_once(monkeypatch, s.service._deps.client, "internal")
        with pytest.raises(ToolFailure) as caught:
            await s.service.delete_game(new.game, owner=OWNER)
        assert caught.value.code == "internal"
        s.host.case_brief(new.game)  # the host still holds the game
        await s.service.delete_game(new.game, owner=OWNER)  # the retry works
        with pytest.raises(GameError):
            s.host.case_brief(new.game)


async def test_close_reporting_an_unknown_game_drops_the_slot(monkeypatch):
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        fail_close_once(monkeypatch, s.service._deps.client, "unknown_game")
        await s.service.delete_game(new.game, owner=OWNER)  # the host already forgot it: fine
        with pytest.raises(ToolFailure) as again:
            s.service.start_turn(new.game, "hello", owner=OWNER)
        assert again.value.code == "unknown_game"  # the slot is gone


async def test_aclose_right_after_start_turn_still_ends_the_stream():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        stream = s.service.start_turn(new.game, "hello", owner=OWNER)
        reader = asyncio.create_task(_collect_stream(stream))
        await s.service.aclose()  # the task is cancelled before its first step
        assert await asyncio.wait_for(reader, timeout=3.0) == []


async def _collect_stream(stream):
    return [event async for event in stream]


# --- the confirm button and the transcript ------------------------------------------------------


async def confirm_id(service: AgentService, game: str, text: str = "I give up") -> str:
    events = await collect(service, game, text)
    [confirm] = [e for e in events if isinstance(e, Confirm)]
    return confirm.pending_id


async def collect_confirm(
    service: AgentService, game: str, pending_id: str, answer: Literal["yes", "no"]
):
    async with asyncio.timeout(10):
        return [e async for e in service.start_confirm(game, pending_id, answer, owner=OWNER)]


async def test_the_confirm_button_runs_the_pending_action_without_a_decision():
    script = Script().understand(intent="give_up")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        pending_id = await confirm_id(s.service, new.game)
        events = await collect_confirm(s.service, new.game, pending_id, "yes")
    assert kinds(events) == ["tool_call", "tool_result", "game_over", "done"]
    assert len(s.decider.calls) == 1  # only the turn that asked


@pytest.mark.parametrize("answer", ["yes", "no"])
async def test_a_confirm_that_is_not_the_one_waiting_is_refused_before_anything_runs(answer):
    script = Script().understand(intent="give_up")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        with pytest.raises(ApiError) as nothing_waiting:
            s.service.start_confirm(new.game, "0" * 32, answer, owner=OWNER)
        await confirm_id(s.service, new.game)
        with pytest.raises(ApiError) as another:
            s.service.start_confirm(new.game, "0" * 32, answer, owner=OWNER)
        assert len(s.service.turns(new.game, owner=OWNER)) == 1  # the refused ones left no trace
    for caught in (nothing_waiting, another):
        assert (caught.value.status, caught.value.code) == (409, "no_such_pending")


async def test_a_confirm_while_a_turn_runs_is_turn_in_progress():
    script = Script().understand(intent="give_up").understand(intent="notebook")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        pending_id = await confirm_id(s.service, new.game)
        gated = GatedDecider(script)
        s.service._deps = replace(s.service._deps, decider=gated)
        running = asyncio.create_task(collect(s.service, new.game, "notes"))
        await gated.entered.wait()
        with pytest.raises(ApiError) as caught:
            s.service.start_confirm(new.game, pending_id, "yes", owner=OWNER)
        gated.release.set()
        await running
    assert caught.value.code == "turn_in_progress"


async def test_the_transcript_keeps_each_turn_with_its_events_in_order():
    script = Script().understand(intent="give_up")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        pending_id = await confirm_id(s.service, new.game, "I quit")
        await collect_confirm(s.service, new.game, pending_id, "no")
        turns = s.service.turns(new.game, owner=OWNER)
    assert [(t.kind, t.text) for t in turns] == [("turn", "I quit"), ("confirm", "no")]
    assert [e.kind for e in turns[0].events] == ["intent", "confirm", "done"]
    assert [e.kind for e in turns[1].events] == ["cancelled", "done"]
    assert all(t.complete for t in turns) and turns[0].turn_id != turns[1].turn_id
    assert datetime.fromisoformat(turns[0].ts).tzinfo is not None


async def test_a_running_turn_shows_in_the_transcript_as_incomplete():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1, owner=OWNER)
        running = asyncio.create_task(collect(s.service, new.game, "notes"))
        await gated.entered.wait()
        [live] = s.service.turns(new.game, owner=OWNER)
        assert (live.text, live.complete, live.events) == ("notes", False, [])
        gated.release.set()
        await running
        [done] = s.service.turns(new.game, owner=OWNER)
    assert done.complete and done.events[-1].kind == "done"


async def test_the_transcript_keeps_only_the_latest_turns(monkeypatch):
    monkeypatch.setattr("gumshoe.api.service.MAX_TURNS_KEPT", 2)
    script = Script()
    for _ in range(3):
        script.understand(intent="notebook")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        for text in ("one", "two", "three"):
            await collect(s.service, new.game, text)
        kept = [t.text for t in s.service.turns(new.game, owner=OWNER)]
    assert kept == ["two", "three"]


async def test_a_cancelled_turn_is_kept_with_its_closing_events():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated, grace_s=2.0) as s:
        new = await s.service.new_game(1, owner=OWNER)
        task = asyncio.create_task(collect(s.service, new.game, "one"))
        await gated.entered.wait()
        await s.service.aclose()
        await task
        [record] = s.service.turns(new.game, owner=OWNER)
    assert record.complete and [e.kind for e in record.events] == ["clarify", "done"]


async def test_a_deleted_games_transcript_is_gone():
    script = Script().understand(intent="notebook")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        await collect(s.service, new.game, "notes")
        await s.service.delete_game(new.game, owner=OWNER)
        with pytest.raises(ToolFailure) as caught:
            s.service.turns(new.game, owner=OWNER)
    assert caught.value.code == "unknown_game"


# --- the game as a reloaded page sees it ---------------------------------------------------------


async def test_state_shows_the_waiting_confirmation_and_no_reveal_while_playing():
    script = Script().understand(intent="give_up")
    async with serving(script) as s:
        new = await s.service.new_game(1, "short", owner=OWNER)
        pending_id = await confirm_id(s.service, new.game)
        state = await s.service.state(new.game, owner=OWNER)
    assert state.pending is not None and state.pending.pending_id == pending_id
    assert (state.pending.kind, state.pending.text) == ("give_up", "Give up and see the answer?")
    assert (state.outcome, state.reveal, state.preset) == ("playing", None, "short")


async def test_a_given_up_game_reads_gave_up_with_its_reveal():
    script = Script().understand(intent="give_up")
    async with serving(script) as s:
        new = await s.service.new_game(1, owner=OWNER)
        pending_id = await confirm_id(s.service, new.game)
        await collect_confirm(s.service, new.game, pending_id, "yes")
        state = await s.service.state(new.game, owner=OWNER)
        [listed] = await s.service.games(owner=OWNER)
    assert state.outcome == listed.outcome == "gave_up"
    assert state.reveal is not None and state.reveal.culprit and state.pending is None


async def test_a_loaded_game_has_no_preset(tmp_path):
    async with serving(Script(), saves_dir=tmp_path) as s:
        new = await s.service.new_game(1, "long", owner=OWNER)
        saved = await s.service.save_game(new.game, owner=OWNER)
        loaded = await s.service.load_game(saved.name, owner=OWNER)
        state = await s.service.state(loaded.game, owner=OWNER)
    assert state.preset is None


async def test_the_games_list_says_when_a_turn_is_running():
    script = Script().understand(intent="notebook")
    gated = GatedDecider(script)
    async with serving(script, decider=gated) as s:
        new = await s.service.new_game(1, owner=OWNER)
        running = asyncio.create_task(collect(s.service, new.game, "notes"))
        await gated.entered.wait()
        [busy] = await s.service.games(owner=OWNER)
        gated.release.set()
        await running
        [free] = await s.service.games(owner=OWNER)
    assert busy.turn_running is True and free.turn_running is False


async def test_saves_come_from_the_injected_lister():
    summary = SaveSummary(
        name="0123456789abcdef", created_at="2026-10-13T10:00:00+00:00", pack="castle",
        status="playing",
    )  # fmt: skip
    async with serving(Script()) as s:
        assert await s.service.saves() == []  # none injected
        s.service._list_saves = lambda: [summary]
        assert await s.service.saves() == [summary]
