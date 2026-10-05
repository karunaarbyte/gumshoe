"""The retry rules written from their definitions, apart from `Retry.fail`, as a test oracle.

A failure names the stage that can fix it. The stage that is restarted is that stage, unless it
has already been restarted `RETRIES` times since a stage before it was last restarted, in which
case the stage before it is tried, and so on; past `roster` the run is exhausted. Then every
stage from the restarted one on has one more stream counter."""

from gumshoe.cases.generate.gen_context import PIPELINE
from gumshoe.cases.generate.pipeline import RETRIES


def restarts_since_an_earlier_stage(history: list[int], stage: int) -> int:
    """How often `stage` was the restarted stage since the last restart of a stage before it."""
    count = 0
    for restarted in reversed(history):
        if restarted < stage:
            break
        count += restarted == stage
    return count


def model(failures: list[str]) -> tuple[list[int], bool]:
    """The restarted stage (as an index into PIPELINE) after each failure, and whether the run
    was exhausted (then the list stops one short of the failures)."""
    history: list[int] = []
    for failing in failures:
        stage = PIPELINE.index(failing)
        while restarts_since_an_earlier_stage(history, stage) + 1 > RETRIES:
            if stage == 0:
                return history, True
            stage -= 1
        history.append(stage)
    return history, False


def counters(history: list[int]) -> tuple[int, ...]:
    """The stream counter of every stage: one per restart at that stage or an earlier one."""
    return tuple(sum(restarted <= stage for restarted in history) for stage in range(len(PIPELINE)))


def retries(history: list[int]) -> tuple[int, ...]:
    return tuple(restarts_since_an_earlier_stage(history, stage) for stage in range(len(PIPELINE)))
