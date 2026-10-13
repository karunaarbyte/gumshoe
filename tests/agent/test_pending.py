import pytest

from gumshoe.agent.config import AgentConfig
from gumshoe.agent.pending import Pending, Step, is_actionable, resolve_pending
from gumshoe.agent.understand import Intent

CONFIG = AgentConfig()


def intent(name="other", p=0.9, confirm=None):
    return Intent(
        name=name,
        target=None,
        intent_confidence=p,
        target_confidence=0.9,
        weight=1.0,
        confirms_pending=confirm,
        decision_id="d",
    )


def pending(reasked=False, kind="accuse"):
    return Pending(kind=kind, line="Confirm?", handles=("a", "b", "c"), reasked=reasked)


def test_without_a_pending_action_everything_is_processed():
    assert resolve_pending(None, intent("search"), CONFIG) is Step.PROCESS


@pytest.mark.parametrize("name", ["other", "meta", "search", "notebook", "give_up"])
def test_a_confident_yes_runs_the_pending_action(name):
    assert resolve_pending(pending(), intent(name, confirm=0.85), CONFIG) is Step.RUN


def test_the_yes_threshold_is_inclusive():
    assert resolve_pending(pending(), intent(confirm=0.8), CONFIG) is Step.RUN
    assert resolve_pending(pending(), intent(confirm=0.79), CONFIG) is Step.REASK


def test_yes_together_with_a_confident_new_accusation_is_ambiguous_and_never_runs():
    step = resolve_pending(pending(), intent("accuse", confirm=0.95), CONFIG)
    assert step is Step.DROP_PROCESS  # the new accusation is processed instead of the old one


def test_yes_with_an_unsure_accuse_still_runs():
    assert resolve_pending(pending(), intent("accuse", p=0.3, confirm=0.95), CONFIG) is Step.RUN


def test_a_no_cancels_and_a_no_with_an_actionable_intent_also_processes_it():
    assert resolve_pending(pending(), intent("other", confirm=0.1), CONFIG) is Step.CANCEL
    assert resolve_pending(pending(), intent("meta", confirm=0.1), CONFIG) is Step.CANCEL
    assert resolve_pending(pending(), intent("search", confirm=0.1), CONFIG) is Step.CANCEL_PROCESS
    assert resolve_pending(pending(), intent("accuse", confirm=0.05), CONFIG) is Step.CANCEL_PROCESS


def test_the_no_threshold_is_inclusive():
    assert resolve_pending(pending(), intent(confirm=0.2), CONFIG) is Step.CANCEL
    assert resolve_pending(pending(), intent(confirm=0.21), CONFIG) is Step.REASK


def test_the_grey_band_with_an_actionable_intent_drops_the_pending_action():
    assert resolve_pending(pending(), intent("search", confirm=0.5), CONFIG) is Step.DROP_PROCESS


def test_the_grey_band_with_an_unsure_or_other_intent_asks_once_then_clears():
    assert resolve_pending(pending(), intent("other", confirm=0.5), CONFIG) is Step.REASK
    assert resolve_pending(pending(), intent("search", p=0.3, confirm=0.5), CONFIG) is Step.REASK
    assert (
        resolve_pending(pending(reasked=True), intent("other", confirm=0.5), CONFIG)
        is Step.CLEAR_PROCESS
    )


def test_a_missing_confirmation_reads_as_grey():
    assert resolve_pending(pending(), intent("other", confirm=None), CONFIG) is Step.REASK


def test_is_actionable_needs_confidence_and_a_real_intent():
    assert is_actionable(intent("search", p=0.6), CONFIG)
    assert not is_actionable(intent("search", p=0.59), CONFIG)
    assert not is_actionable(intent("other"), CONFIG) and not is_actionable(intent("meta"), CONFIG)
