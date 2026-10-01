import json

import pytest

from gumshoe.cases.model.serialize import dump_case
from gumshoe.cases.tools.cli import build_parser, main
from tests.cases.fixtures import build_case, build_pack, build_strict_case
from tests.cases.mutations import MUTATIONS


@pytest.fixture
def good(tmp_path):
    path = tmp_path / "case.json"
    path.write_bytes(dump_case(build_case()))
    return path


def test_parser_defaults_and_choices():
    args = build_parser().parse_args(["validate", "c.json"])
    assert args.profile == "strict" and args.pack is None and args.dev is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["validate", "c.json", "--profile", "weird"])
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_a_clean_case_exits_zero_and_says_so(good, capsys):
    assert main(["validate", str(good), "--profile", "custom"]) == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_a_broken_case_exits_one_and_lists_issues_by_code(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_bytes(dump_case(MUTATIONS["DANGLING_REF"].apply(build_case())))
    assert main(["validate", str(path), "--profile", "custom"]) == 1
    out = capsys.readouterr().out
    assert "DANGLING_REF" in out and "f_key" in out and "error" in out


def test_spoiler_issues_are_hidden_without_dev_and_counted(tmp_path, capsys):
    path = tmp_path / "spoil.json"
    path.write_bytes(dump_case(MUTATIONS["TRUTH_RULED_OUT"].apply(build_case())))
    assert main(["validate", str(path), "--profile", "custom"]) == 1
    hidden = capsys.readouterr().out
    assert "TRUTH_RULED_OUT" not in hidden and "spoiler issue" in hidden
    assert main(["validate", str(path), "--profile", "custom", "--dev"]) == 1
    assert "TRUTH_RULED_OUT" in capsys.readouterr().out


def test_a_pack_file_enables_the_pack_rules(tmp_path, capsys):
    case_path, pack_path = tmp_path / "c.json", tmp_path / "p.json"
    case_path.write_bytes(dump_case(build_strict_case()))
    pack_path.write_text(build_pack().model_dump_json())
    assert (
        main(["validate", str(case_path), "--pack", str(pack_path)]) == 1
    )  # unknown preset "tiny" in the built-in table
    assert "SPEC_MISMATCH" in capsys.readouterr().out
    assert main(["validate", str(case_path)]) == 1
    assert "PACK_RULES_SKIPPED" in capsys.readouterr().out


def test_unreadable_or_invalid_input_exits_two_without_a_traceback(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "missing.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["validate", str(bad)]) == 2
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"id": "x"}))
    assert main(["validate", str(wrong)]) == 2
    err = capsys.readouterr().err
    assert err.count("error:") == 3 and "Traceback" not in err


def test_public_api_exports():
    import gumshoe.cases as cases

    for name in (
        "Case",
        "Pack",
        "Profile",
        "Severity",
        "Issue",
        "Report",
        "CATALOGUE",
        "validate_case",
        "load_case",
        "dump_case",
        "skeleton_digest",
        "skin_hash",
    ):
        assert hasattr(cases, name), name
    assert set(cases.__all__) >= {"Case", "validate_case", "load_case"}
