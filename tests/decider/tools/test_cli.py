import json

import pytest
from pydantic import ValidationError

from gumshoe.decider.tools.cli import build_parser, load_questions
from gumshoe.decider.contract.models import NoulQuestion
from gumshoe.decider.contract.samples import DEMO_QUESTIONS


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
    path.write_text(json.dumps({"x": {"type": "choice", "instructions": "?", "criteria": {"a": "1"}}}))
    with pytest.raises(ValidationError):
        load_questions(path)
