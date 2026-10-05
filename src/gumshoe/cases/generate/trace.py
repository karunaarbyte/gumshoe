"""What a generation run did, and the error raised when it cannot finish."""

from dataclasses import dataclass

from gumshoe.cases.validate.report import Report


@dataclass(frozen=True)
class Attempt:
    """One attempt (a strict-validator call, or a stage that raised) and what the controller
    decided after it."""

    number: int  # 1 for the first attempt
    first_stage: str  # the stage this attempt (re)started from
    counters: tuple[int, ...]  # the stream counter of every stage, in `PIPELINE` order
    codes: tuple[str, ...]  # the error codes the validator reported, sorted; empty on success
    restart: str | None  # the stage the controller restarts from next; None when it stops
    detail: str = ""  # a stage's own error message (the code is then `STAGE_ERROR`)


@dataclass(frozen=True)
class GenerationTrace:
    attempts: tuple[Attempt, ...]

    def lines(self) -> list[str]:
        """One line per attempt, for a developer: number, counters, codes and the restart stage."""
        return [
            f"{a.number:2} from {a.first_stage:9} n={list(a.counters)} "
            f"{','.join(a.codes) or 'ok'}"
            + (f" ({a.detail})" if a.detail else "")
            + (f" -> restart {a.restart}" if a.restart else "")
            for a in self.attempts
        ]


class CaseGenerationError(Exception):
    """No valid case came out: an issue no stage can fix appeared, or the budget or the
    escalation ran out. The trace holds every attempt; the report is the last validator call's
    (None when the last attempt ended in a stage's own error)."""

    def __init__(self, message: str, trace: GenerationTrace, report: Report | None = None) -> None:
        super().__init__(message)
        self.trace = trace
        self.report = report
