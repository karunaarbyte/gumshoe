import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SCRIPT = """
import hashlib
from gumshoe.cases.model.serialize import dump_case, skeleton_digest, skin_hash
from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import TINY_PRESETS, build_case, build_pack, build_strict_case
from tests.cases.mutations import MUTATIONS, run_mutation

h = hashlib.sha256()
case = build_case()
h.update(dump_case(case))
h.update(skeleton_digest(case).encode())
h.update(skin_hash(case).encode())
h.update(validate(case, profile=Profile.CUSTOM).canonical())
h.update(validate(build_strict_case(), build_pack(), Profile.STRICT, TINY_PRESETS).canonical())
for code in sorted(MUTATIONS):
    h.update(code.encode()); h.update(run_mutation(MUTATIONS[code]).canonical())
print(h.hexdigest())
"""


def run_with_seed(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def test_dumps_digests_and_reports_are_byte_identical_across_hash_seeds():
    digests = {seed: run_with_seed(seed) for seed in ("0", "1", "12345", "random")}
    assert len(set(digests.values())) == 1, digests
    assert len(next(iter(digests.values()))) == 64


def test_the_fixture_digest_matches_the_golden_file_in_a_fresh_process():
    golden = (ROOT / "tests" / "cases" / "golden" / "manor_small.digest").read_text().strip()
    code = (
        "from gumshoe.cases.model.serialize import skeleton_digest\n"
        "from tests.cases.fixtures import build_case\n"
        "print(skeleton_digest(build_case()))\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": "3", "PYTHONPATH": str(ROOT)}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == golden
