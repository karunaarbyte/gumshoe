import json

import pytest
from mcp.client import Client

import gumshoe.mcp_server.__main__ as main_module
import gumshoe.mcp_server.host as host_module
from gumshoe.cases import BuiltinPackError, PackInfo, bundled_pack, pack_info
from gumshoe.cases.tools.cli import main as cli_main
from gumshoe.mcp_server import GameError, GameHost
from gumshoe.mcp_server.saves import path_for
from gumshoe.mcp_server.tools import build_server
from tests.mcp_server.helpers import SeqIds


def host_in(folder):
    return GameHost(ids=SeqIds(), saves_dir=folder)


def error_of(call):
    with pytest.raises(GameError) as err:
        call()
    return err.value


def test_a_new_game_says_its_pack_and_preset(tmp_path):
    new = host_in(tmp_path).new_game(3, "standard", "castle")
    assert new.pack == "castle" and new.preset == "standard"


def test_an_unknown_pack_is_refused_without_echoing_the_id(tmp_path):
    err = error_of(lambda: host_in(tmp_path).new_game(1, "standard", "nope"))
    assert err.code == "bad_argument" and err.message == "unknown setting"
    assert "nope" not in err.message


def test_a_preset_the_pack_does_not_host_names_the_ones_it_does(tmp_path):
    err = error_of(lambda: host_in(tmp_path).new_game(1, "nonesuch", "castle"))
    assert err.code == "bad_argument" and "standard" in err.message and "castle" in err.message


def test_save_and_load_keep_the_pack_and_preset(tmp_path):
    host = host_in(tmp_path)
    new = host.new_game(2, "short", "castle")
    loaded = host.load_game(host.save_game(new.game).name)
    assert (loaded.pack, loaded.preset) == ("castle", "short")


def test_a_second_pack_round_trips(tmp_path, monkeypatch):
    real = bundled_pack("castle")
    assert real is not None
    info = pack_info("castle")
    assert info is not None
    other = real.model_copy(update={"id": "castle2"})
    other_info = PackInfo(id="castle2", title="Castle Two", blurb="b", presets=info.presets)
    monkeypatch.setattr(host_module, "bundled_pack", lambda i: other if i == "castle2" else None)
    monkeypatch.setattr(host_module, "pack_info", lambda i: other_info if i == "castle2" else None)
    host = host_in(tmp_path)
    new = host.new_game(1, "standard", "castle2")
    assert new.pack == "castle2"
    loaded = host.load_game(host.save_game(new.game).name)
    assert loaded.pack == "castle2" and loaded.preset == "standard"


def test_a_save_naming_a_pack_the_server_lacks_is_a_bad_save(tmp_path):
    host = host_in(tmp_path)
    ref = host.save_game(host.new_game(1).game)
    path = path_for(tmp_path, ref.name)
    data = json.loads(path.read_text())
    data["pack"] = "gone"
    path.write_text(json.dumps(data))
    err = error_of(lambda: host.load_game(ref.name))
    assert err.code == "bad_save" and err.message == "that save names a pack this server lacks"


async def test_the_tool_defaults_to_the_default_pack(tmp_path):
    async with Client(build_server(host_in(tmp_path))) as client:
        result = await client.call_tool("new_game", {"seed": 1})
    assert not result.is_error and result.structured_content["pack"] == "castle"


def test_the_cli_still_generates_on_the_default_pack(capsys):
    assert cli_main(["generate", "1", "--preset", "standard"]) == 0


@pytest.mark.parametrize("argv", [["generate", "1"], ["smoke", "--seeds", "1"]])
def test_a_broken_registry_stops_the_cli(monkeypatch, capsys, argv):
    import gumshoe.cases.tools.cli as cli_module

    def boom():
        raise BuiltinPackError("pack 'x' has 1 issue(s)")

    monkeypatch.setattr(cli_module, "bundled_packs", boom)
    assert cli_main(argv) == 2
    assert "pack 'x' has 1 issue(s)" in capsys.readouterr().err


def test_a_broken_registry_stops_the_mcp_server(monkeypatch):
    def boom():
        raise BuiltinPackError("pack 'x' has 1 issue(s)")

    monkeypatch.setattr(main_module, "bundled_packs", boom)
    with pytest.raises(SystemExit) as exit_:
        main_module.main([])
    assert "pack 'x'" in str(exit_.value)
