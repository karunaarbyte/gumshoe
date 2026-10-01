"""The context handed to every rule group: the case, the pack, the profile and shared indexes."""

from dataclasses import dataclass, field
from functools import cached_property

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import Axis
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.graph import Graph, build_graph
from gumshoe.cases.validate.reach import Reach, compute_reach
from gumshoe.cases.validate.report import Hint, Issue, Profile, Severity


@dataclass
class Ctx:
    case: Case
    pack: Pack | None
    profile: Profile
    presets: dict[str, PresetDef] = field(default_factory=lambda: dict(PRESETS))

    @cached_property
    def index(self) -> CaseIndex:
        return CaseIndex.of(self.case)

    @cached_property
    def graph(self) -> Graph:
        return build_graph(self.index)

    @cached_property
    def reach(self) -> Reach:
        return compute_reach(self.index)

    def issue(self, code: str, *subjects: str, axis: Axis | None = None, **params: object) -> Issue:
        spec = CATALOGUE[code]  # KeyError for an unknown code: groups cannot invent codes
        severity: Severity = (
            spec.severity_imported if self.profile is Profile.IMPORTED else spec.severity_strict
        )
        pairs = tuple(sorted((key, str(value)) for key, value in params.items()))
        return Issue(
            code=code,
            severity=severity,
            group=spec.group,
            subjects=tuple(str(s) for s in subjects),
            axis=axis,
            params=pairs,
            hint=Hint(spec.hint, pairs),
            spoiler=spec.spoiler,
            fix_stage=spec.fix_stage,
        )
