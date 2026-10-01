"""Generate shadow-mode traffic: push a fixed set of player inputs through a decider."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from gumshoe.decider import DEMO_PLAYER_INPUTS, DEMO_QUESTIONS, Decider, DeciderError


@dataclass(frozen=True)
class BatteryResult:
    attempted: int
    failed: int  # decisions where nothing could answer (the failures are recorded in the DB too)
    last_error: str | None


async def run_battery(
    decider: Decider,
    rounds: int,
    *,
    settle: Callable[[], Awaitable[None]] | None = None,
) -> BatteryResult:
    """Run every demo input `rounds` times. A failing decision is counted, not fatal.

    `settle` runs after every decision (success or failure). Pass the shadow decider's `drain` so
    its background call finishes before the next decision starts: a local model works through
    requests one at a time, so firing decisions back to back would queue the shadow calls (losing
    some at shutdown and inflating their latency). Real play is paced by a human; this imitates it.
    """
    attempted = failed = 0
    last_error: str | None = None
    for _ in range(rounds):
        for text in DEMO_PLAYER_INPUTS:
            attempted += 1
            try:
                await decider.decide(text, DEMO_QUESTIONS, node="battery")
            except DeciderError as exc:
                failed += 1
                last_error = str(exc)
            finally:
                if settle is not None:
                    await settle()
    return BatteryResult(attempted=attempted, failed=failed, last_error=last_error)
