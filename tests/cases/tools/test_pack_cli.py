import pytest

from gumshoe.cases.tools.builtin import BuiltinPackError, load_builtin_pack
from gumshoe.cases.tools.cli import main
from gumshoe.cases.tools.pack_cli import run_pack_check
from tests.packs.fixtures import BASE_TOML
from tests.packs.mutations import replace


def lines_of(path):
    out: list[str] = []
    code = run_pack_check(path, out.append)
    return code, out


def test_the_real_presets_do_not_know_the_test_pack_so_it_reports_one_issue(tmp_path):
    path = tmp_path / "tiny.toml"
    path.write_text(BASE_TOML)
    code, out = lines_of(path)
    assert code == 1 and out[0].split()[:2] == ["error", "PRESET_UNSUPPORTED"]
    assert out[-1] == "1 error(s)"


def test_a_clean_pack_file_prints_ok_and_exits_zero(tmp_path):
    path = tmp_path / "t.toml"
    path.write_text(replace('presets = ["tiny"]', "presets = []")(BASE_TOML))
    code, out = lines_of(path)
    assert (code, out) == (0, ["ok"])


def test_issues_print_code_path_message_and_suggestion(tmp_path):
    path = tmp_path / "t.toml"
    path.write_text(
        replace('presets = ["tiny"]', "presets = []")(
            replace('location_kinds = ["study"]', 'location_kinds = ["studdy"]')(BASE_TOML)
        )
    )
    code, out = lines_of(path)
    assert code == 1
    assert "UNKNOWN_LOCATION_KIND" in out[0] and "scene_types.study_murder" in out[0]
    assert "studdy" in out[1] and out[2].lstrip().startswith("did you mean 'study'?")


def test_an_unreadable_file_exits_two_and_says_so(tmp_path, capsys):
    assert run_pack_check(tmp_path / "missing.toml") == 2
    assert "cannot read" in capsys.readouterr().err


def test_the_command_is_wired_into_the_main_parser(tmp_path, capsys):
    path = tmp_path / "t.toml"
    path.write_text(replace('presets = ["tiny"]', "presets = []")(BASE_TOML))
    assert main(["packs", "check", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_a_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main(["packs"])


def test_an_unknown_builtin_pack_name_is_a_clear_error():
    with pytest.raises(BuiltinPackError, match="no bundled pack named 'nope'"):
        load_builtin_pack("nope")
