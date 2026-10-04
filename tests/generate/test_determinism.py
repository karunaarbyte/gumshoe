import os
import subprocess
import sys
from pathlib import Path

from tests.generate.update_golden import stage_digests

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = """
import json
from tests.generate.update_golden import stage_digests
print(json.dumps(stage_digests(), sort_keys=True))
"""


def run_with_hash_seed(hash_seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_stage_outputs_are_byte_identical_across_processes_and_hash_seeds():
    import json

    outputs = {seed: run_with_hash_seed(seed) for seed in ("0", "1", "12345", "random")}
    assert len(set(outputs.values())) == 1
    assert json.loads(next(iter(outputs.values()))) == stage_digests()
