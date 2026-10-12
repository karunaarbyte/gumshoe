"""Random tool-call sequences against generated castle cases: invariants and spoiler checks."""

import random

import pytest

from gumshoe.cases.core.ids import make_id
from gumshoe.mcp_server import GameError, GameHost
from tests.mcp_server.helpers import SeqIds, castle_case, explore_all, true_triple

SEEDS = range(1, 7)
PRESETS = ("short", "standard", "long")
FIRST_SALT = "0000000000000001"
STEPS = 40
SCRIPT_STEP = 25
FIELDS_THAT_MEAN_TRUTH = ('"truthful"', '"effects"', '"claim"', '"exposed_by"', '"requires"')
PLAYER_VIEWS = {"search", "interrogate", "records", "notebook", "persona", "brief", "reply", "save"}
UNCHECKED = {"reveal", "give_up"}  # the only places the truth may appear


def texts_of(notebook):
    return {f.text for s in notebook.sections for f in s.facts}


def raw_ids(case):
    return {
        *(x.id for x in case.suspects),
        *(x.id for x in case.locations),
        *(x.id for x in case.methods),
        *(x.id for x in case.motives),
        *(x.id for x in case.facts),
        *(x.id for x in case.timeline),
    }


def play(seed, preset, folder):
    """One random game. Returns the log; asserts every invariant on the way."""
    host = GameHost(ids=SeqIds(), saves_dir=folder)
    new = host.new_game(seed, preset)
    game, brief = new.game, new.brief
    case = castle_case(seed, preset)
    ids = raw_ids(case)
    hidden = [make_id("h", FIRST_SALT, entity) for entity in sorted(ids)]
    places = [x.handle for x in brief.locations] + ["h_bogus"]
    people = [x.handle for x in brief.suspects] + ["h_bogus"]
    kinds = [None, *(k.key for k in brief.record_kinds), "nonsense"]
    truth_names = (
        next(s.display_name for s in case.suspects if s.id == case.truth.who),
        next(m.label for m in case.methods if m.id == case.truth.how),
        next(m.label for m in case.motives if m.id == case.truth.why),
    )
    rng = random.Random(seed * 31 + len(preset))
    log: list[str] = []
    attempts, status = 3, "playing"
    known: set[str] = set()
    last_q = None

    def pick(axis):
        options = host.nameable(game, axis).options
        if options and rng.random() < 0.7:
            return rng.choice(options).handle
        return rng.choice([*hidden, "h_bogus", ""])

    def scripted():
        """Explore everything, then win (seed % 3 == 0) or keep missing (seed % 3 == 1)."""
        explore_all(host, game)
        who, how, why = true_triple(host, game, case)
        if seed % 3 == 0:
            return "accuse", host.accuse(game, who, how, why, confirmed=True)
        wrongs = [c.handle for c in host.nameable(game, "who").options if c.handle != who]
        result = host.accuse(game, wrongs[0], how, why, confirmed=True)
        for handle in wrongs[1:]:
            if host.case_brief(game).status != "playing":
                break
            result = host.accuse(game, handle, how, why, confirmed=True)
        return "accuse", result

    def act(step):
        nonlocal last_q
        if step == SCRIPT_STEP and seed % 3 != 2 and status == "playing":
            return scripted()
        action = rng.choice(
            ["search"] * 3 + ["interrogate"] * 3 + ["records"] * 3 + ["notebook", "brief"]
            + ["nameable", "describe", "accuse", "accuse", "persona", "reply", "reveal", "save"]
            + ["acc_q", "interpret"]
            + (["give_up"] if step >= STEPS - 5 and rng.random() < 0.3 else [])
        )  # fmt: skip
        if action == "search":
            return action, host.search(game, rng.choice(places))
        if action == "interrogate":
            return action, host.interrogate(game, rng.choice(people))
        if action == "records":
            return action, host.check_records(game, rng.choice(places + people), rng.choice(kinds))
        if action == "notebook":
            return action, host.notebook(game)
        if action == "brief":
            return action, host.case_brief(game)
        if action == "nameable":
            return action, host.nameable(game, rng.choice(["who", "how", "why"]))
        if action == "describe":
            return action, host.describe_accusation(game, pick("who"), pick("how"), pick("why"))
        if action == "accuse":
            parts = (pick("who"), pick("how"), pick("why"))
            return action, host.accuse(game, *parts, confirmed=rng.random() < 0.7)
        if action == "persona":
            return action, host.persona_brief(game, rng.choice(people))
        if action == "reply":
            reply = rng.choice(["I was home.", f"It was {truth_names[1]}.", "Ask the cook."])
            return action, host.check_reply(game, rng.choice(people), "Tell me.", reply)
        if action == "acc_q":
            last_q = host.accusation_questions(
                game, rng.choice(["Boris did it", "the rope", "nonsense", ""])
            )
            return action, last_q
        if action == "interpret":
            if last_q is None:
                last_q = host.accusation_questions(game, "anything")
                return "acc_q", last_q
            axis = rng.choice(sorted(last_q.questions))
            letters = sorted(last_q.questions[axis].criteria)
            picks = {rng.choice(letters): rng.choice([0.9, 0.5, 0.1])}
            result = host.interpret_accusation(game, {axis: picks})
            last_q = None
            return action, result
        if action == "save":
            return action, host.save_game(game)
        if action == "give_up":
            return action, host.give_up(game)
        return action, host.reveal(game)

    for step in range(STEPS):
        try:
            action, result = act(step)
        except GameError as err:
            assert err.code in {"game_over", "not_over", "unknown_handle"}
            if err.code == "game_over":
                assert status != "playing"
            if err.code == "not_over":
                assert status == "playing"
            log.append(f"E:{err.code}")
            continue
        blob = result.model_dump_json()
        log.append(blob)
        now = host.case_brief(game)
        assert now.attempts_left <= attempts and now.attempts_left >= 0
        if action != "accuse" or result.status != "resolved":
            assert now.attempts_left == attempts  # only a resolved accusation costs an attempt
        attempts = now.attempts_left
        assert status == "playing" or now.status == status  # an ended game stays ended
        status = now.status
        notebook = texts_of(host.notebook(game))
        assert known <= notebook  # discovered facts only grow
        known = notebook
        if action not in UNCHECKED:
            assert not [i for i in ids if i in blob], f"a raw id reached the {action} result"
            assert not [f for f in FIELDS_THAT_MEAN_TRUTH if f in blob], (
                f"a truth field reached the {action} result"
            )
            unheld = [s.secret_text for s in case.suspects if s.secret_text not in notebook]
            assert not [t for t in unheld if t and t in blob], (
                f"an unfound secret leaked into the {action} result"
            )
        if action in PLAYER_VIEWS:
            assert not all(name in blob for name in truth_names), (
                "the true triple appeared as a unit"
            )
    return log


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", SEEDS)
def test_random_play_keeps_every_invariant_and_leaks_nothing(seed, preset, tmp_path):
    assert play(seed, preset, tmp_path)


@pytest.mark.parametrize("preset", PRESETS)
def test_the_same_random_play_gives_byte_identical_output(preset, tmp_path):
    assert play(2, preset, tmp_path / "a") == play(2, preset, tmp_path / "b")
