from enum import StrEnum


class FixStage(StrEnum):
    """Which generator stage can fix an issue (each catalogue code declares one)."""

    ROSTER = "roster"
    TRUTH = "truth"
    TIMELINE = "timeline"
    FACTS = "facts"
    PLACEMENT = "placement"
    GATING = "gating"
    SKIN = "skin"
    ASSEMBLE = "assemble"
    PACK = "pack"
    NONE = "none"
