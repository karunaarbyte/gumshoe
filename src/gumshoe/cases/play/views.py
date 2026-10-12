"""What a player surface may see. Imports nothing from gumshoe: pydantic and stdlib only.

`status` and `kind` fields are plain strings whose values are listed in each docstring.
"""

from pydantic import BaseModel, ConfigDict


class View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LocationView(View):
    number: int
    handle: str
    name: str
    description: str
    locked: bool


class SuspectView(View):
    number: int
    handle: str
    name: str
    description: str
    locked: bool


class RecordKindView(View):
    key: str  # passed back to check_records
    label: str


class PlayerCaseView(View):
    intro: str
    locations: tuple[LocationView, ...]
    suspects: tuple[SuspectView, ...]
    record_kinds: tuple[RecordKindView, ...]
    attempts_left: int
    status: str  # playing | won | lost


class FactView(View):
    handle: str
    text: str
    speaker: str | None  # display name
    source: str  # display label of where it was found
    contradicted: bool  # true only for a lie whose exposer is held


class ContradictionView(View):
    lie: str  # handle
    exposer: str  # handle
    text: str


class SourceResult(View):
    """kind: search | interrogate | records. status: ok | nothing_new | locked | unknown."""

    kind: str
    label: str
    status: str
    new_facts: tuple[FactView, ...] = ()
    contradictions: tuple[ContradictionView, ...] = ()
    opened: tuple[str, ...] = ()  # display labels of sources that now have something new
    kinds: tuple[str, ...] = ()  # record kinds that contributed (check_records only)


class NotebookFact(View):
    handle: str
    text: str
    speaker: str | None
    relates_to: tuple[str, ...]  # suspect display names, never an effect kind
    contradicted: bool


class NotebookSection(View):
    source: str
    facts: tuple[NotebookFact, ...]


class NotebookView(View):
    sections: tuple[NotebookSection, ...]
    contradictions: tuple[ContradictionView, ...]


class ParsedAccusation(View):
    """Candidate handles per part; None = the player has not (clearly) named one."""

    who: str | None = None
    how: str | None = None
    why: str | None = None


class Candidate(View):
    handle: str
    name: str
    warned: bool = False  # the player holds a rule-out against this candidate


class AxisOptions(View):
    axis: str  # who | how | why
    options: tuple[Candidate, ...]


class ResolvedPart(View):
    axis: str
    name: str


class AxisProblem(View):
    """reason: unclear (no clear candidate; also a how/why candidate the gate has not opened,
    so hidden ones cannot be probed) | not_permitted (a suspect the gate does not allow yet)."""

    axis: str
    reason: str
    options: tuple[Candidate, ...]  # what may be named right now


class AccusationPlan(View):
    resolved: tuple[ResolvedPart, ...]
    problems: tuple[AxisProblem, ...]
    warnings: tuple[str, ...]
    repeat: bool
    can_confirm: bool
    confirmation: str  # empty unless can_confirm


class AccusationResult(View):
    """status: needs_confirmation | not_permitted | repeat | resolved."""

    status: str
    correct: int | None
    attempts_left: int
    game: str  # playing | won | lost
    message: str


class RevealView(View):
    culprit: str
    method: str
    motive: str
    secret: str


class PersonaBrief(View):
    """What the agent needs to voice one suspect. `says` holds the statements the player has
    already drawn out of this suspect (held facts found by questioning them), nothing else."""

    name: str  # display name, "<name> the <noun>"
    traits: tuple[str, ...]
    style: str
    says: tuple[str, ...]  # neutral order (by text)
    smalltalk_allow: tuple[str, ...]  # the pack's neutral words


class ReplyViolation(View):
    category: str  # who | how | why | unknown_suspect: a category and a count, never the word
    count: int


class ReplyCheck(View):
    ok: bool
    violations: tuple[ReplyViolation, ...]
