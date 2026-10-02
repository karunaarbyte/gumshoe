"""Pack issues: plain frozen data with a deterministic order."""

from dataclasses import dataclass
from enum import StrEnum


class PackSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class PackIssue:
    code: str
    severity: PackSeverity
    stage: int
    path: str  # a TOML key path such as methods.dagger.traces[wound].location_kinds[crypt]
    message: str
    suggestion: str = ""  # did-you-mean or fix text

    def sort_key(self) -> tuple[int, str, str, str]:
        return (self.stage, self.code, self.path, self.message)
