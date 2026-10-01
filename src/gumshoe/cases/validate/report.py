"""Issues and reports: plain frozen data, deterministic ordering, canonical serialisation."""

from dataclasses import dataclass
from enum import StrEnum

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.enums import FixStage
from gumshoe.cases.model.enums import Axis


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Profile(StrEnum):
    STRICT = "strict"  # generated cases: every rule is an error
    IMPORTED = "imported"  # blurb path: statistical rules are warnings, no pack
    CUSTOM = "custom"  # hand-built fixtures: strict severities, pack rules silently off


class HintOp(StrEnum):
    RENAME_ID = "rename_id"
    FIX_REF = "fix_ref"
    ADD_FACT = "add_fact"
    ADD_EXPOSER = "add_exposer"
    REMOVE_EFFECT = "remove_effect"
    RELABEL = "relabel"
    MOVE_FACT = "move_fact"
    RAISE_DEPTH = "raise_depth"
    LOWER_DEPTH = "lower_depth"
    BREAK_CYCLE = "break_cycle"
    ADJUST_COUNT = "adjust_count"
    REPLACE_TEMPLATE = "replace_template"
    DROP_CANDIDATE = "drop_candidate"
    FIX_SPEC = "fix_spec"
    FIX_PACK = "fix_pack"
    NONE = "none"


Params = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Hint:
    op: HintOp
    args: Params = ()


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    group: int
    subjects: tuple[str, ...]
    axis: Axis | None
    params: Params
    hint: Hint
    spoiler: bool
    fix_stage: FixStage

    def sort_key(self) -> tuple[int, str, tuple[str, ...], str, Params]:
        return (
            self.group,
            self.code,
            self.subjects,
            self.axis.value if self.axis else "",
            self.params,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "group": self.group,
            "subjects": list(self.subjects),
            "axis": self.axis.value if self.axis else None,
            "params": {k: v for k, v in self.params},
            "hint": {"op": self.hint.op.value, "args": {k: v for k, v in self.hint.args}},
            "spoiler": self.spoiler,
            "fix_stage": self.fix_stage.value,
        }


@dataclass(frozen=True)
class Report:
    profile: Profile
    issues: tuple[Issue, ...]
    skipped_groups: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

    def codes(self) -> frozenset[str]:
        return frozenset(i.code for i in self.issues)

    def of_code(self, code: str) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.code == code)

    def canonical(self) -> bytes:
        return canonical_json(
            {
                "profile": self.profile.value,
                "skipped_groups": list(self.skipped_groups),
                "issues": [i.to_dict() for i in self.issues],
            }
        )
