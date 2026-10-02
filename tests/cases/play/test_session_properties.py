import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from gumshoe.cases.model.enums import Axis
from gumshoe.cases.play.session import GameOver, GameSession
from gumshoe.cases.play.views import ParsedAccusation
from gumshoe.cases.validate.context import Ctx
from gumshoe.cases.validate.groups import g01_structure
from gumshoe.cases.validate.report import Profile, Severity
from tests.cases.fixtures import build_case
from tests.cases.fuzz import corrupt

ROOT = Path(__file__).resolve().parents[3]
TRUTH_LABELS = ("poisoned in the wine", "to cover a gambling debt")


def entity_ids(case) -> list[str]:
    return [
        *(x.id for x in case.suspects),
        *(x.id for x in case.locations),
        *(x.id for x in case.methods),
        *(x.id for x in case.motives),
        *(x.id for x in case.facts),
        *(x.id for x in case.timeline),
    ]


def run(seed: int) -> tuple[list[str], GameSession]:
    case = build_case()
    ids = entity_ids(case)
    rng = random.Random(seed)
    s = GameSession(case, "salt")
    brief = s.brief()
    places = [x.handle for x in brief.locations] + ["h_bogus"]
    people = [x.handle for x in brief.suspects] + ["h_bogus"]
    cand = {axis: [s._handles[c] for c in s._ix.candidates[axis]] for axis in Axis}  # noqa: SLF001
    held_sizes: list[int] = []
    log: list[str] = []
    attempts_used = 0
    last_left = s.attempts_left
    for _ in range(40):
        before = s.state_json()
        # views that must never carry an id or a truth label (the accusation views may name
        # a candidate, but only one nameable() offered, so they are not part of this blob)
        blobs: list[str] = []
        try:
            action = rng.choice(
                ["search"] * 3
                + ["ask"] * 3
                + ["records"] * 3
                + ["accuse", "accuse_ok", "accuse_ok", "describe", "notebook", "reply"]
                + ["give_up"] * (1 if rng.random() < 0.15 else 0)
            )
            if action == "search":
                blobs.append(s.search(rng.choice(places)).model_dump_json())
            elif action == "ask":
                blobs.append(s.interrogate(rng.choice(people)).model_dump_json())
            elif action == "records":
                result = s.check_records(
                    rng.choice(places + people), rng.choice([None, "ledger", "x"])
                )
                blobs.append(result.model_dump_json())
            elif action == "reply":
                check = s.check_reply(
                    rng.choice(people), "Tell me.", rng.choice(["I was home.", "It was poison."])
                )
                assert s.state_json() == before
                blobs.append(check.model_dump_json())
            elif action == "give_up":
                s.give_up()
            elif action in ("accuse", "accuse_ok", "describe"):
                picks = {}
                for axis in Axis:
                    named = [o.handle for o in s.nameable(axis.value).options]
                    pool = named if named and rng.random() < 0.7 else cand[axis]
                    picks[axis.value] = rng.choice([*pool, None])
                parsed = ParsedAccusation(**picks)
                if action == "describe":
                    s.describe_accusation(parsed)
                    assert s.state_json() == before
                else:
                    verdict = s.accuse(parsed, confirmed=action == "accuse_ok")
                    log.append(verdict.status)
                    if verdict.status == "resolved":
                        attempts_used += 1
                    else:
                        assert s.state_json() == before
            else:
                blobs.append(s.notebook().model_dump_json())
        except GameOver:
            break
        blobs.append(s.brief().model_dump_json())
        text = "\n".join(blobs)
        assert [i for i in ids if i in text] == []
        for label in TRUTH_LABELS:
            assert label not in text
        held_sizes.append(len(json.loads(s.state_json())["discovered"]))
        assert s.attempts_left == 3 - attempts_used
        assert s.attempts_left <= last_left
        last_left = s.attempts_left
    assert held_sizes == sorted(held_sizes)  # discovered facts only grow
    return log, s


def test_random_action_sequences_never_raise_and_keep_the_invariants():
    for seed in range(200):
        run(seed)


def test_identical_actions_give_identical_outcomes():
    for seed in range(20):
        a, sa = run(seed)
        b, sb = run(seed)
        assert a == b and sa.state_json() == sb.state_json()


SCRIPT = """
import hashlib
from gumshoe.cases.play.session import GameSession
from gumshoe.cases.play.views import ParsedAccusation
from tests.cases.fixtures import build_case

s = GameSession(build_case(), "salt")
out = [s.brief().model_dump_json()]
brief = s.brief()
for _ in range(2):
    for loc in brief.locations:
        out.append(s.search(loc.handle).model_dump_json())
for sus in brief.suspects:
    out.append(s.interrogate(sus.handle).model_dump_json())
for x in (*brief.locations, *brief.suspects):
    out.append(s.check_records(x.handle).model_dump_json())
out.append(s.notebook().model_dump_json())
picks = {}
for axis in ("who", "how", "why"):
    options = s.nameable(axis)
    out.append(options.model_dump_json())
    picks[axis] = options.options[0].handle
parsed = ParsedAccusation(**picks)
out.append(s.describe_accusation(parsed).model_dump_json())
out.append(s.accuse(parsed, confirmed=True).model_dump_json())
prompt = s.accusation_prompt("Boris did it")
out.append(repr((prompt.state, sorted(prompt.keys.items()))))
out.append("".join(q.model_dump_json() for _, q in sorted(prompt.questions.items())))
print(hashlib.sha256("\\n".join(out).encode()).hexdigest())
"""


def test_views_are_identical_across_hash_seeds():
    digests = []
    for hash_seed in ("0", "1"):
        done = subprocess.run(
            [sys.executable, "-c", SCRIPT],
            cwd=ROOT,
            env={"PYTHONHASHSEED": hash_seed, "PATH": "", "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=True,
        )
        digests.append(done.stdout.strip())
    assert len(digests[0]) == len(hashlib.sha256().hexdigest())
    assert digests[0] == digests[1]


def group1_clean(case) -> bool:
    ctx = Ctx(case=case, pack=None, profile=Profile.CUSTOM)
    return not any(i.severity is Severity.ERROR for i in g01_structure.run(ctx))


def play_through(case) -> None:
    s = GameSession(case, "salt")
    brief = s.brief()
    for _ in range(2):
        for loc in brief.locations:
            s.search(loc.handle)
    for sus in brief.suspects:
        s.interrogate(sus.handle)
    for loc in brief.locations:
        s.check_records(loc.handle)
    for sus in brief.suspects:
        s.check_records(sus.handle)
    s.notebook()
    picks = {}
    for axis in Axis:
        options = s.nameable(axis.value).options
        picks[axis.value] = options[0].handle if options else None
    parsed = ParsedAccusation(**picks)
    s.describe_accusation(parsed)
    s.accuse(parsed)
    s.accuse(parsed, confirmed=True)
    if s.status == "playing":
        s.accuse(ParsedAccusation(who="h_bogus"))
    s.accusation_prompt("anything")
    if s.status == "playing":
        s.give_up()
    s.reveal()


def test_the_session_never_raises_on_group_one_clean_corruptions():
    rng = random.Random(1)
    played = 0
    for _ in range(3000):
        case = corrupt(build_case(), rng)
        if group1_clean(case):
            play_through(case)
            played += 1
    assert played > 100
