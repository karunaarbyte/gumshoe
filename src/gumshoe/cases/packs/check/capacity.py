"""Stage 6: capacity and presets. Filled in by a later task."""

from collections.abc import Mapping

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PresetDef
from gumshoe.cases.packs.issues import PackIssue


def check(pack: Pack, presets: Mapping[str, PresetDef]) -> list[PackIssue]:
    return []
