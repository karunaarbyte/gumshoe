import pytest

from gumshoe.config import Settings
from gumshoe.decider import (
    DEMO_PLAYER_INPUTS,
    DeciderConnectionError,
    DecisionResult,
    ShadowDecider,
)
from gumshoe.stats import __main__ as stats_main
from gumshoe.stats.battery import BatteryResult, run_battery
from gumshoe.stats.store import SqliteStatsStore
from tests.decider.fakes import FakeDecider, FakeRecorder


@pytest.fixture
def result(load_fixture):
    return DecisionResult.model_validate(load_fixture("nimble_all_types.response.json"))


def test_inputs_cover_clear_ambiguous_compound_and_nonsense():
    assert len(DEMO_PLAYER_INPUTS) >= 10
    assert len(set(DEMO_PLAYER_INPUTS)) == len(DEMO_PLAYER_INPUTS)
    assert "asdf" in DEMO_PLAYER_INPUTS
    assert all(text.strip() for text in DEMO_PLAYER_INPUTS)


async def test_run_battery_runs_every_input_every_round(result):
    decider = FakeDecider("jev", result)
    outcome = await run_battery(decider, rounds=2)
    assert outcome == BatteryResult(
        attempted=2 * len(DEMO_PLAYER_INPUTS), failed=0, last_error=None
    )
    assert decider.nodes == ["battery"] * outcome.attempted


class FlakyDecider:
    """Fails for chosen inputs, succeeds for the rest."""

    name = "jev"

    def __init__(self, result, failing):
        self._result, self._failing = result, failing
        self.seen = []

    async def decide(self, state, questions, *, node="adhoc"):
        self.seen.append(state)
        if state in self._failing:
            raise DeciderConnectionError("jev", f"flaky on {state!r}")
        return self._result

    async def aclose(self):
        pass


async def test_a_failing_input_does_not_abort_the_run(result):
    failing = {DEMO_PLAYER_INPUTS[3], DEMO_PLAYER_INPUTS[7]}
    decider = FlakyDecider(result, failing)
    outcome = await run_battery(decider, rounds=2)
    assert len(decider.seen) == 2 * len(DEMO_PLAYER_INPUTS)  # every input was still tried
    assert outcome.attempted == 2 * len(DEMO_PLAYER_INPUTS)
    assert outcome.failed == 4  # 2 failing inputs x 2 rounds
    assert outcome.last_error is not None and "flaky" in outcome.last_error


def test_parser_defaults_and_rounds():
    parser = stats_main.build_parser()
    assert parser.parse_args(["battery"]).rounds == 1
    assert parser.parse_args(["battery", "--rounds", "3"]).rounds == 3


@pytest.mark.parametrize("bad", ["0", "-2", "x", "1.5"])
def test_parser_rejects_bad_rounds(bad):
    with pytest.raises(SystemExit):
        stats_main.build_parser().parse_args(["battery", "--rounds", bad])


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        stats_main.build_parser().parse_args([])


def test_main_records_every_input_for_both_backends(monkeypatch, tmp_path, result, capsys):
    db = tmp_path / "decisions.db"
    settings = Settings(_env_file=None, stats_db_path=db, jev_api_key="k")

    def fake_make_decider(settings, backend=None, recorder=None):
        return ShadowDecider(FakeDecider("jev", result), FakeDecider("nimble", result), recorder)

    monkeypatch.setattr(stats_main, "get_settings", lambda: settings)
    monkeypatch.setattr(stats_main, "make_decider", fake_make_decider)
    assert stats_main.main(["battery", "--rounds", "2"]) == 0
    calls = SqliteStatsStore(db).fetch_calls()
    assert len(calls) == 2 * len(DEMO_PLAYER_INPUTS) * 2  # rounds x inputs x backends
    assert {c.node for c in calls} == {"battery"}
    out = capsys.readouterr().out
    assert f"ran {2 * len(DEMO_PLAYER_INPUTS)} decisions (0 failed)" in out


def test_main_exits_nonzero_with_a_clean_error_when_every_decision_fails(
    monkeypatch, tmp_path, capsys
):
    settings = Settings(_env_file=None, stats_db_path=tmp_path / "d.db", jev_api_key="k")
    down = DeciderConnectionError("jev", "cannot reach")

    def fake_make_decider(settings, backend=None, recorder=None):
        return ShadowDecider(FakeDecider("jev", error=down), None, recorder or FakeRecorder())

    monkeypatch.setattr(stats_main, "get_settings", lambda: settings)
    monkeypatch.setattr(stats_main, "make_decider", fake_make_decider)
    assert stats_main.main(["battery"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "cannot reach" in err and "Traceback" not in err
    assert f"all {len(DEMO_PLAYER_INPUTS)} decisions failed" in err


def test_main_succeeds_but_reports_partial_failures(monkeypatch, tmp_path, result, capsys):
    settings = Settings(_env_file=None, stats_db_path=tmp_path / "d.db", jev_api_key="k")
    flaky = FlakyDecider(result, {DEMO_PLAYER_INPUTS[0]})

    def fake_make_decider(settings, backend=None, recorder=None):
        return ShadowDecider(flaky, None, recorder or FakeRecorder())

    monkeypatch.setattr(stats_main, "get_settings", lambda: settings)
    monkeypatch.setattr(stats_main, "make_decider", fake_make_decider)
    assert stats_main.main(["battery"]) == 0
    assert f"ran {len(DEMO_PLAYER_INPUTS)} decisions (1 failed)" in capsys.readouterr().out


def test_main_reports_a_missing_key_cleanly(monkeypatch, tmp_path, capsys):
    settings = Settings(_env_file=None, stats_db_path=tmp_path / "d.db")  # primary jev, no key
    monkeypatch.setattr(stats_main, "get_settings", lambda: settings)
    assert stats_main.main(["battery"]) == 1
    assert "JEV_API_KEY" in capsys.readouterr().err
