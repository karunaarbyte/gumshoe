import os
import random
import re
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

import pytest

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.catalogue import PACK_CATALOGUE, make
from gumshoe.cases.packs.check import capacity, hygiene, matching, plausibility, refs, templates
from gumshoe.cases.packs.issues import PackIssue
from gumshoe.cases.packs.loader import load_pack
from gumshoe.cases.packs.runner import check_pack
from tests.packs.fixtures import BASE_TOML, CAPACITY, TEST_PRESETS
from tests.packs.mutations import MUTATIONS

ROOT = Path(__file__).resolve().parents[2]


def test_every_pack_code_has_a_mutation():
    assert set(MUTATIONS) == set(PACK_CATALOGUE)


def test_the_base_pack_is_clean_through_the_whole_pipeline():
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    assert pack is not None
    assert check_pack(pack, TEST_PRESETS) == ()


def test_an_empty_pack_never_crashes_any_stage():
    for presets in ((), ("tiny",), ("short", "standard")):
        pack = Pack(id="e", capacity=CAPACITY, presets=presets)
        issues = check_pack(pack, TEST_PRESETS)
        assert isinstance(issues, tuple)


_STAGES = {
    2: refs,
    3: templates,
    4: hygiene,
    5: plausibility,
    6: capacity,
    7: matching,
}


def _run_with_issues_at(monkeypatch: pytest.MonkeyPatch, failing: set[int]) -> list[int]:
    """Replace every stage's check with a fake that records its call; the stages in `failing`
    return one synthetic issue. Returns the stages that ran, in order."""
    calls: list[int] = []

    def fake(stage: int):
        def check(*_args: object) -> list[PackIssue]:
            calls.append(stage)
            if stage not in failing:
                return []
            return [make("PRESET_UNSUPPORTED", f"stage{stage}", reason="x")]

        return check

    for stage, module in _STAGES.items():
        monkeypatch.setattr(module, "check", fake(stage))
    check_pack(Pack(id="e", capacity=CAPACITY), TEST_PRESETS)
    return calls


def test_a_stage_2_issue_stops_every_later_stage(monkeypatch):
    assert _run_with_issues_at(monkeypatch, {2}) == [2]


def test_a_stage_5_issue_stops_stages_6_and_7_but_not_3_and_4(monkeypatch):
    assert _run_with_issues_at(monkeypatch, {5}) == [2, 3, 4, 5]


def test_stage_3_and_4_issues_do_not_stop_stages_6_and_7(monkeypatch):
    assert _run_with_issues_at(monkeypatch, {3, 4}) == [2, 3, 4, 5, 6, 7]


def _castle_text() -> str:
    return files("gumshoe.cases.packs").joinpath("castle.toml").read_text(encoding="utf-8")


_WORD = re.compile(r"[a-z]+")
_QUOTED = re.compile(r'"[^"\\]*"')


def _mutate_line(
    rng: random.Random, mutated: list[str], words: list[str], structural: bool
) -> None:
    """One seeded edit. A structural edit (drop, dup, garble, swap) mostly breaks the schema; a
    content edit swaps a word inside a quoted string, so the pack usually still loads and the
    later stages see odd values."""
    i = rng.randrange(len(mutated))
    op = rng.choice(("drop", "dup", "garble", "swap")) if structural else "word"
    if op == "drop":
        del mutated[i]
    elif op == "dup":
        mutated.insert(i, mutated[i])
    elif op == "garble":
        text = mutated[i]
        cut = rng.randrange(len(text) + 1)
        mutated[i] = text[:cut] + rng.choice('{}[]"=\\#.\n\t ') + text[cut:]
    elif op == "swap":
        j = rng.randrange(len(mutated))
        mutated[i], mutated[j] = mutated[j], mutated[i]
    else:
        text = mutated[i]
        spans = [
            w for q in _QUOTED.finditer(text) for w in _WORD.finditer(text, q.start(), q.end())
        ]
        if spans:
            w = rng.choice(spans)
            mutated[i] = text[: w.start()] + rng.choice(words) + text[w.end() :]


@pytest.mark.parametrize("source", ["base", "castle"])
def test_loading_mutated_text_never_raises(source):
    # the castle runs on the small test presets: stages 6 and 7 still run on every mutant that
    # gets that far, but the real seven-suspect preset would make 300 loads too slow
    text = BASE_TOML if source == "base" else _castle_text()
    lines, words = text.splitlines(), sorted(set(_WORD.findall(text)))
    rng = random.Random(7)
    loaded = 0
    start = time.perf_counter()
    for k in range(300):
        mutated = list(lines)
        for _ in range(rng.randint(1, 4)):
            _mutate_line(rng, mutated, words, structural=k % 2 == 1)
        result = load_pack("\n".join(mutated).encode(), TEST_PRESETS)
        assert isinstance(result.issues, tuple)
        loaded += result.pack is not None
    assert loaded >= 100, loaded  # enough mutants get past stage 1 to exercise stages 2 to 7
    assert time.perf_counter() - start < 5


def test_issue_order_is_identical_across_hash_seeds():
    script = (
        "from gumshoe.cases.packs.loader import load_pack\n"
        "from tests.packs.fixtures import BASE_TOML, TEST_PRESETS\n"
        "from tests.packs.mutations import MUTATIONS\n"
        "for code in sorted(MUTATIONS):\n"
        "    r = load_pack(MUTATIONS[code].apply(BASE_TOML).encode(), TEST_PRESETS)\n"
        "    print(code, [(i.code, i.path, i.message) for i in r.issues])\n"
    )
    outputs = set()
    for seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
        run = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.add(run.stdout)
    assert len(outputs) == 1
