"""Generate shadow-mode traffic: push a fixed set of player inputs through a decider."""

from dataclasses import dataclass

from gumshoe.decider import DEMO_PLAYER_INPUTS, DEMO_QUESTIONS, Decider, DeciderError


@dataclass(frozen=True)
class BatteryResult:
    attempted: int
    failed: int  # decisions where nothing could answer (the failures are recorded in the DB too)
    last_error: str | None


async def run_battery(decider: Decider, rounds: int) -> BatteryResult:
    """Run every demo input `rounds` times. A failing decision is counted, not fatal."""
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
    return BatteryResult(attempted=attempted, failed=failed, last_error=last_error)
