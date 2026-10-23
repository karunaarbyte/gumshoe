import os
import time
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
    text = (tmp_path / f"{NAME}.owner").read_text().splitlines()[0]
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


def make_save(tmp_path, name):
    (tmp_path / f"{name}.json").write_text("{}")


def test_the_sidecar_has_the_owner_tag_then_the_ip_tag(tmp_path):
    o = owners_in(tmp_path)
    o.claim(NAME, "alice", "1.1.1.1")
    first, second = (tmp_path / f"{NAME}.owner").read_text().splitlines()
    assert len(first) == len(second) == 32 and first != second
    assert o.owns(NAME, "alice")


def test_counts_by_owner_and_by_ip(tmp_path):
    o = owners_in(tmp_path)
    rows = [("alice", "1.1.1.1"), ("alice", "1.1.1.1"), ("bob", "1.1.1.1"), ("carol", "2.2.2.2")]
    for i, (owner, ip) in enumerate(rows):
        o.claim(f"{i:016x}", owner, ip)
    assert (o.count_owned("alice"), o.count_owned("bob"), o.count_owned("nobody")) == (2, 1, 0)
    assert (o.count_ip("1.1.1.1"), o.count_ip("2.2.2.2"), o.count_ip("3.3.3.3")) == (3, 1, 0)


def test_an_old_one_line_sidecar_still_counts_for_its_owner_but_for_no_ip(tmp_path):
    o = owners_in(tmp_path)
    (tmp_path / f"{NAME}.owner").write_text(sessions().owner_tag("alice"))
    assert o.owns(NAME, "alice") and o.count_owned("alice") == 1 and o.count_ip("1.1.1.1") == 0


def test_a_damaged_sidecar_counts_for_nobody_and_does_not_raise(tmp_path):
    o = owners_in(tmp_path)
    (tmp_path / f"{NAME}.owner").write_bytes(b"\xff\xfe\x00garbage")
    assert o.count_owned("alice") == 0 and o.count_ip("1.1.1.1") == 0 and not o.owns(NAME, "a")


def test_delete_removes_both_files_and_tolerates_missing_ones(tmp_path):
    o = owners_in(tmp_path)
    make_save(tmp_path, NAME)
    o.claim(NAME, "alice")
    o.delete(NAME)
    assert not (tmp_path / f"{NAME}.json").exists() and not (tmp_path / f"{NAME}.owner").exists()
    o.delete(NAME)  # nothing left: no error
    with pytest.raises(ValueError):
        o.delete("../x")


def test_purge_removes_old_saves_and_orphan_sidecars_only(tmp_path):
    o = owners_in(tmp_path)
    old, new, orphan = "a" * 16, "b" * 16, "c" * 16
    for name in (old, new):
        make_save(tmp_path, name)
        o.claim(name, "alice")
    o.claim(orphan, "alice")  # a sidecar whose save is gone
    long_ago = time.time() - 40 * 86400
    os.utime(tmp_path / f"{old}.json", (long_ago, long_ago))
    assert o.purge(30 * 86400.0) == 1
    assert not (tmp_path / f"{old}.json").exists() and not (tmp_path / f"{old}.owner").exists()
    assert (tmp_path / f"{new}.json").exists() and (tmp_path / f"{new}.owner").exists()
    assert not (tmp_path / f"{orphan}.owner").exists()


def test_purge_also_removes_an_old_save_that_has_no_owner_sidecar(tmp_path):
    o = owners_in(tmp_path)
    make_save(tmp_path, NAME)  # no claim: made before owners existed, or the server stopped
    long_ago = time.time() - 40 * 86400
    os.utime(tmp_path / f"{NAME}.json", (long_ago, long_ago))
    make_save(tmp_path, "b" * 16)  # a fresh unowned save is kept
    assert o.purge(30 * 86400.0) == 1
    assert not (tmp_path / f"{NAME}.json").exists() and (tmp_path / f"{'b' * 16}.json").exists()


def test_purge_leaves_files_that_are_not_saves_alone(tmp_path):
    o = owners_in(tmp_path)
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "README").write_text("x")
    long_ago = time.time() - 400 * 86400
    for f in tmp_path.iterdir():
        os.utime(f, (long_ago, long_ago))
    assert o.purge(86400.0) == 0 and len(list(tmp_path.iterdir())) == 2


def test_purge_does_not_follow_symlinks_and_a_missing_folder_is_fine(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "precious.json"
    target.write_text("{}")
    long_ago = time.time() - 400 * 86400
    os.utime(target, (long_ago, long_ago))
    folder = tmp_path / "saves"
    folder.mkdir()
    (folder / f"{NAME}.json").symlink_to(target)
    o = SaveOwners(folder, sessions())
    assert o.purge(86400.0) == 0
    assert target.exists() and (folder / f"{NAME}.json").is_symlink()
    assert SaveOwners(tmp_path / "nope", sessions()).purge(1.0) == 0
