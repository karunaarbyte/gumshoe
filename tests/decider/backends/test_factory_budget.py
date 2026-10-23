import pytest
from pydantic import SecretStr

import gumshoe.decider.backends.factory as factory
from gumshoe.config import Settings
from gumshoe.decider import BudgetDecider, DeciderConfigError, ShadowDecider, make_decider
from gumshoe.decider.backends.client import SystemOneClient
from gumshoe.decider.contract.models import DecisionResult, Usage
from gumshoe.decider.contract.samples import DEMO_QUESTIONS, DEMO_STATE
from gumshoe.decider.shadow.budget import MeteredDecider
from tests.decider.fakes import FakeDecider, FakeRecorder
from tests.decider.shadow.test_budget import MemoryLedger


def settings(**kw):
    return Settings(_env_file=None, jev_api_key=SecretStr("k"), **kw)


def test_with_a_ledger_and_caps_the_budget_stack_is_built():
    d = make_decider(settings(), recorder=FakeRecorder(), ledger=MemoryLedger())
    assert isinstance(d, BudgetDecider) and d.name == "jev" and d.mode == "normal"


def test_without_a_ledger_it_is_the_plain_shadow_decider():
    assert isinstance(make_decider(settings(), recorder=FakeRecorder()), ShadowDecider)


def test_with_both_caps_off_it_is_the_plain_shadow_decider():
    d = make_decider(
        settings(jev_daily_tokens=0, jev_ip_daily_tokens=0),
        recorder=FakeRecorder(),
        ledger=MemoryLedger(),
    )
    assert isinstance(d, ShadowDecider)


def test_when_nimble_is_the_primary_there_is_no_budget():
    s = Settings(_env_file=None, shadow_run=False)
    assert isinstance(
        make_decider(s, recorder=FakeRecorder(), ledger=MemoryLedger()), ShadowDecider
    )


def test_an_explicit_backend_is_never_wrapped():
    d = make_decider(settings(), backend="nimble", recorder=FakeRecorder(), ledger=MemoryLedger())
    assert isinstance(d, ShadowDecider)


def test_a_missing_jev_key_still_fails_at_construction():
    with pytest.raises(DeciderConfigError):
        make_decider(Settings(_env_file=None), recorder=FakeRecorder(), ledger=MemoryLedger())


@pytest.mark.parametrize(
    ("s", "backend", "ledger"),
    [
        (settings(), None, None),
        (settings(jev_daily_tokens=0, jev_ip_daily_tokens=0), None, MemoryLedger()),
        (Settings(_env_file=None, shadow_run=False), None, MemoryLedger()),
        (settings(), "jev", MemoryLedger()),
        (settings(), "nimble", MemoryLedger()),
    ],
)
def test_without_a_budget_the_stack_is_unchanged(s, backend, ledger):
    """No budget: the same ShadowDecider as before, around the bare client (never metered)."""
    d = make_decider(s, backend=backend, recorder=FakeRecorder(), ledger=ledger)
    assert type(d) is ShadowDecider
    assert type(d._primary) is SystemOneClient


def test_only_the_jev_primary_is_metered():
    d = make_decider(settings(), recorder=FakeRecorder(), ledger=MemoryLedger())
    assert isinstance(d, BudgetDecider)
    normal, fallback = d._normal, d._fallback
    assert isinstance(normal, ShadowDecider) and isinstance(fallback, ShadowDecider)
    assert isinstance(normal._primary, MeteredDecider) and normal._primary.name == "jev"
    assert type(normal._shadow) is SystemOneClient and normal._shadow.name == "nimble"
    assert type(fallback._primary) is SystemOneClient and fallback._primary.name == "nimble"
    assert fallback._shadow is None


@pytest.fixture
def result(load_fixture):
    base = DecisionResult.model_validate(load_fixture("jev_all_types.response.json"))
    return base.model_copy(update={"usage": Usage(input_tokens=1000, output_tokens=5)})


async def test_a_fallback_call_adds_nothing_to_the_meter(result, monkeypatch):
    """Built by the factory with fake clients: Jev calls count, Nimble-alone calls never do."""
    made: list[FakeDecider] = []

    def fake_client(s, profile):
        made.append(FakeDecider(profile.name, result))
        return made[-1]

    monkeypatch.setattr(factory, "_client", fake_client)
    recorder = FakeRecorder()
    d = make_decider(
        settings(jev_daily_tokens=1000, jev_ip_daily_tokens=0),
        recorder=recorder,
        ledger=MemoryLedger(),
    )
    assert isinstance(d, BudgetDecider)
    meter = d._meter
    await meter.load()
    await d.decide(DEMO_STATE, DEMO_QUESTIONS)  # on Jev: 1000 tokens, the cap is reached
    assert (meter.total(), d.mode) == (1000, "slow")
    await d.decide(DEMO_STATE, DEMO_QUESTIONS)  # on Nimble alone
    await d.decide(DEMO_STATE, DEMO_QUESTIONS)
    assert meter.total() == 1000
    jev, shadow, alone = made
    assert (jev.name, shadow.name, alone.name) == ("jev", "nimble", "nimble")
    assert (len(jev.nodes), len(alone.nodes)) == (1, 2)
    await d.aclose()
    assert all(c.closed for c in made)
