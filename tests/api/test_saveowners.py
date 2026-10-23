from functools import partial

import pytest

from gumshoe.agent import ToolFailure
from gumshoe.api.errors import BAD_SAVE_MESSAGE
from gumshoe.api.saveowners import SaveOwners
from gumshoe.api.session import Sessions
from gumshoe.api.wiring import save_index
from tests.agent.fakes import Script
from tests.api.helpers import OWNER, serving

NAME = "0123456789abcdef"


def sessions():
    return Sessions(b"k" * 32, secure=False)


def owners_in(tmp_path):
    return SaveOwners(tmp_path, sessions())


def test_a_claimed_save_is_owned_by_its_claimer_only(tmp_path):
    o = owners_in(tmp_path)
    o.claim(NAME, "alice")
    assert o.owns(NAME, "alice") and not o.owns(NAME, "bob")


def test_an_unclaimed_or_badly_named_save_is_owned_by_nobody(tmp_path):
    o = owners_in(tmp_path)
    assert not o.owns(NAME, "alice")
    for bad in ("../x", "short", "ZZZZZZZZZZZZZZZZ", ""):
        assert not o.owns(bad, "alice")
    with pytest.raises(ValueError):
        o.claim("../x", "alice")


def test_the_sidecar_holds_a_tag_not_the_session_id(tmp_path):
    owners_in(tmp_path).claim(NAME, "alice-session-id")
    text = (tmp_path / f"{NAME}.owner").read_text()
    assert "alice" not in text and len(text) == 32


def test_a_damaged_sidecar_means_not_owned(tmp_path):
    (tmp_path / f"{NAME}.owner").write_bytes(b"\xff\xfe not text")
    assert not owners_in(tmp_path).owns(NAME, "alice")


async def test_saving_claims_the_save_and_only_the_owner_can_list_or_load_it(tmp_path):
    owners = owners_in(tmp_path)
    async with serving(
        Script(), saves_dir=tmp_path, owners=owners, list_saves=partial(save_index, tmp_path)
    ) as s:
        new = await s.service.new_game(1, owner="alice")
        saved = await s.service.save_game(new.game, owner="alice")
        assert [x.name for x in await s.service.saves(owner="alice")] == [saved.name]
        assert await s.service.saves(owner="bob") == []
        with pytest.raises(ToolFailure) as bob:
            await s.service.load_game(saved.name, owner="bob")
        with pytest.raises(ToolFailure) as missing:
            await s.service.load_game(NAME, owner="bob")
        assert (bob.value.code, bob.value.message) == ("bad_save", BAD_SAVE_MESSAGE)
        assert (bob.value.code, bob.value.message) == (missing.value.code, missing.value.message)
        again = await s.service.load_game(saved.name, owner="alice")
        assert again.game != new.game


async def test_a_save_made_before_owners_existed_belongs_to_nobody(tmp_path):
    async with serving(Script(), saves_dir=tmp_path) as s:  # no owners yet
        new = await s.service.new_game(1, owner=OWNER)
        saved = await s.service.save_game(new.game, owner=OWNER)
    owners = owners_in(tmp_path)  # a server started after the change
    async with serving(
        Script(), saves_dir=tmp_path, owners=owners, list_saves=partial(save_index, tmp_path)
    ) as s:
        assert await s.service.saves(owner=OWNER) == []
        with pytest.raises(ToolFailure) as caught:
            await s.service.load_game(saved.name, owner=OWNER)
    assert caught.value.code == "bad_save"
