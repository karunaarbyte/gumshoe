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
        "GameSession",
        "load_session",
    ):
        assert hasattr(cases, name), name
    assert set(cases.__all__) >= {
        "Case",
        "validate_case",
        "load_case",
        "GameSession",
        "load_session",
    }


def test_parser_knows_play_and_simulate():
    args = build_parser().parse_args(["play", "c.json", "--salt", "s"])
    assert args.salt == "s"
    assert build_parser().parse_args(["simulate", "c.json"]).command == "simulate"


def test_simulate_command_prints_the_report(good, capsys):
    assert main(["simulate", str(good)]) == 0
    assert "blind-guess win rate" in capsys.readouterr().out


def test_play_command_runs_a_session_on_scripted_input(good, capsys, monkeypatch):
    answers = iter(["q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert main(["play", str(good), "--salt", "s"]) == 0
    assert "Goodbye" in capsys.readouterr().out


def test_play_and_simulate_report_unreadable_input_with_exit_two(tmp_path, capsys):
    assert main(["play", str(tmp_path / "missing.json")]) == 2
    assert main(["simulate", str(tmp_path / "missing.json")]) == 2


def test_play_refuses_a_structurally_broken_case(tmp_path, capsys, monkeypatch):
    broken = tmp_path / "broken.json"
    broken.write_bytes(dump_case(MUTATIONS["DANGLING_REF"].apply(build_case())))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("game started"))
    assert main(["play", str(broken), "--salt", "s"]) == 2
    assert "DANGLING_REF" in capsys.readouterr().err


def test_simulate_refuses_a_structurally_broken_case(tmp_path, capsys):
    broken = tmp_path / "broken.json"
    broken.write_bytes(dump_case(MUTATIONS["DANGLING_REF"].apply(build_case())))
    assert main(["simulate", str(broken)]) == 2
    captured = capsys.readouterr()
    assert "DANGLING_REF" in captured.err and captured.out == ""


def test_a_handle_collision_makes_play_exit_two(good, capsys, monkeypatch):
    monkeypatch.setattr("gumshoe.cases.play.session.make_id", lambda *parts: "h_same")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("game started"))
    assert main(["play", str(good), "--salt", "s"]) == 2
    assert "handle collision" in capsys.readouterr().err


def test_generate_writes_a_case_that_validates_with_its_pack(tmp_path, capsys):
    from gumshoe.cases.model.serialize import load_case
    from gumshoe.cases.validate.report import Profile
    from gumshoe.cases.validate.runner import validate
    from tests.generate.helpers import castle

    path = tmp_path / "case.json"
    assert main(["generate", "5", "--preset", "short", "-o", str(path)]) == 0
    case = load_case(path.read_bytes())
    assert case.seed == 5 and case.spec.preset == "short"
    assert validate(case, castle(), Profile.STRICT).issues == ()
    assert main(["validate", str(path), "--profile", "custom"]) == 0
    assert capsys.readouterr().out.strip().endswith("ok")


def test_generate_prints_the_case_when_no_file_is_given(capsys):
    from gumshoe.cases.model.serialize import load_case

    assert main(["generate", "2"]) == 0
    assert load_case(capsys.readouterr().out.encode()).spec.preset == "standard"


def test_generate_text_prints_a_readable_case(capsys):
    assert main(["generate", "3", "--preset", "short", "--text"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Lord ") and "Truth: " in out and "Suspects:" in out
    assert "Places:" in out and "Question " in out and "[false]" in out
    assert "{" not in out and "}" not in out
    assert "Read the " in out and "chapel_register" not in out


def test_generate_refuses_an_unknown_pack_and_an_unwritable_file(tmp_path, capsys):
    assert main(["generate", "1", "--pack", "nowhere"]) == 2
    assert "no bundled pack" in capsys.readouterr().err
    assert main(["generate", "1", "-o", str(tmp_path / "missing" / "case.json")]) == 2
    assert "cannot write" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build_parser().parse_args(["generate", "1", "--preset", "epic"])


def test_smoke_reports_the_attempts_and_exits_zero_when_all_is_well(capsys):
    assert main(["smoke", "--preset", "short", "--seeds", "6"]) == 0
    out = capsys.readouterr().out
    assert "short: 6 cases, attempts mean 1.00 max 1, 0 failed" in out
    assert "1 attempt(s): 6 case(s)" in out
    assert main(["smoke", "--pack", "nowhere"]) == 2
    assert main(["smoke", "--preset", "short", "--seeds", "0"]) == 1  # no case is not a pass
    assert "no case was made" in capsys.readouterr().out


def test_generate_reports_a_generation_failure_on_stderr(monkeypatch, capsys):
    from gumshoe.cases.generate.trace import CaseGenerationError, GenerationTrace
    from gumshoe.cases.tools import cli

    def refuse(seed, preset, pack):
        raise CaseGenerationError("no stage can fix PACK_MISMATCH", GenerationTrace(()))

    monkeypatch.setattr(cli, "generate", refuse)
    assert main(["generate", "1"]) == 2
    assert "no stage can fix PACK_MISMATCH" in capsys.readouterr().err


def test_smoke_exits_one_when_the_criterion_fails(monkeypatch, capsys):
    from gumshoe.cases.tools import cli
    from gumshoe.cases.tools.gen_dev import SmokeReport

    slow = SmokeReport("short", ((1, 1), (3, 2)), (("FACTS_X", 4),), ())  # mean 2.33
    monkeypatch.setattr(cli, "smoke", lambda pack, preset, seeds: slow)
    assert main(["smoke", "--preset", "short"]) == 1
    out = capsys.readouterr().out
    assert "mean 2.33 max 3" in out and "FACTS_X: 4" in out
