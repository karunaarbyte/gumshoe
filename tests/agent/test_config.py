import pytest

from gumshoe.agent.config import AgentConfig


def test_defaults_match_the_spec():
    c = AgentConfig()
    assert (c.confidence_gate, c.confirm_gate, c.max_redrafts, c.dramatic_from) == (
        0.6,
        0.8,
        3,
        2.5,
    )
    assert (c.model_default, c.model_dramatic) == ("ministral-3:14b", "gemma4:12b")


@pytest.mark.parametrize(
    "bad",
    [
        {"confirm_gate": 0.5},  # the yes and no bands would meet
        {"confirm_gate": 0.4},
        {"confirm_gate": 1.01},
        {"confidence_gate": 0.0},
        {"confidence_gate": 1.5},
        {"max_redrafts": -1},
        {"max_text": 0},
        {"notebook_cap": 0},
        {"exchanges_kept": -1},
    ],
)
def test_invalid_values_are_refused(bad):
    with pytest.raises(ValueError):
        AgentConfig(**bad)


def test_the_gate_can_be_exactly_one():
    assert AgentConfig(confirm_gate=1.0).confirm_gate == 1.0
