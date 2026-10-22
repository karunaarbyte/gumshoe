import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import UNKNOWN_GAME
from tests.agent.fakes import Script
from tests.api.helpers import OWNER, serving

STRANGER = "owner-2"


async def test_the_owner_sees_the_game_and_a_stranger_gets_the_missing_game_error():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        assert (await s.service.state(new.game, owner=OWNER)).brief == new.brief
        with pytest.raises(ToolFailure) as stranger:
            await s.service.state(new.game, owner=STRANGER)
        with pytest.raises(ToolFailure) as missing:
            await s.service.state("nope", owner=OWNER)
    assert (stranger.value.code, stranger.value.message) == (
        missing.value.code,
        missing.value.message,
    )
    assert stranger.value.message == UNKNOWN_GAME


@pytest.mark.parametrize("method", ["state", "turns", "save_game", "delete_game"])
async def test_every_game_method_refuses_a_stranger(method):
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        call = getattr(s.service, method)
        with pytest.raises(ToolFailure) as caught:
            result = call(new.game, owner=STRANGER)
            if hasattr(result, "__await__"):
                await result
        assert caught.value.code == "unknown_game"
        # the stranger's attempt changed nothing for the owner
        assert (await s.service.state(new.game, owner=OWNER)).outcome == "playing"


async def test_a_stranger_cannot_start_a_turn_or_confirm():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        with pytest.raises(ToolFailure):
            s.service.start_turn(new.game, "search", owner=STRANGER)
        with pytest.raises(ToolFailure):
            s.service.start_confirm(new.game, "p1", "yes", owner=STRANGER)


async def test_the_list_holds_only_the_callers_games_and_asks_the_engine_about_no_one_else(
    monkeypatch,
):
    async with serving(Script()) as s:
        mine = await s.service.new_game(1, owner=OWNER)
        theirs = await s.service.new_game(2, owner=STRANGER)
        asked: list[str] = []
        real = s.service._deps.client.case_brief

        async def counting(game):
            asked.append(game)
            return await real(game)

        monkeypatch.setattr(s.service._deps.client, "case_brief", counting)
        listed = await s.service.games(owner=OWNER)
    assert [g.game for g in listed] == [mine.game]
    assert asked == [mine.game] and theirs.game not in asked


async def test_a_deleted_game_is_gone_for_its_owner_and_stays_unreachable_for_others():
    async with serving(Script()) as s:
        new = await s.service.new_game(1, owner=OWNER)
        await s.service.delete_game(new.game, owner=OWNER)
        for who in (OWNER, STRANGER):
            with pytest.raises(ToolFailure):
                await s.service.state(new.game, owner=who)
