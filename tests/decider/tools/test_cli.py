import json

import pytest
from pydantic import ValidationError

from gumshoe.config import Settings
from gumshoe.decider.contract.models import NoulQuestion
from gumshoe.decider.contract.samples import DEMO_QUESTIONS
from gumshoe.decider.tools import cli
from gumshoe.decider.tools.cli import build_parser, load_questions, main


def test_parser_ask_with_backend():
    args = build_parser().parse_args(["ask", "hello", "--backend", "jev"])
    assert args.state == "hello"
    assert args.backend == "jev"


def test_parser_compare_has_no_backend_flag():
    args = build_parser().parse_args(["compare", "hello"])
    assert args.state == "hello"
    assert not hasattr(args, "backend")


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_default_questions_are_the_demo_set():
    assert load_questions(None) == DEMO_QUESTIONS


def test_questions_load_from_json_file(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"is_clue": {"type": "noul", "instructions": "Is this a clue?"}}))
    questions = load_questions(path)
    assert isinstance(questions["is_clue"], NoulQuestion)


def test_invalid_questions_file_raises(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps({"x": {"type": "choice", "instructions": "?", "criteria": {"a": "1"}}})
    )
    with pytest.raises(ValidationError):
        load_questions(path)


@pytest.fixture
def nimble_only(monkeypatch):
    """Point the CLI at Nimble settings that never touch .env or the network."""
    settings = Settings(_env_file=None, decider_primary="nimble", decider_shadow=None)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)


def test_blank_state_prints_a_clean_error_not_a_traceback(nimble_only, capsys):
    assert main(["ask", "   "]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "state must not be blank" in err
    assert "Traceback" not in err


def test_bad_questions_file_prints_a_clean_error(nimble_only, tmp_path, capsys):
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps({"x": {"type": "choice", "instructions": "?", "criteria": {"a": "1"}}})
    )
    assert main(["ask", "hello", "--questions", str(path)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "x.choice.criteria" in err
    assert "Traceback" not in err


def test_unreadable_questions_file_prints_a_clean_error(nimble_only, tmp_path, capsys):
    assert main(["ask", "hello", "--questions", str(tmp_path / "missing.json")]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_missing_jev_key_is_a_clean_error(monkeypatch, capsys):
    settings = Settings(_env_file=None, decider_primary="jev", decider_shadow=None)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert main(["ask", "hello"]) == 1
    assert "JEV_API_KEY" in capsys.readouterr().err
