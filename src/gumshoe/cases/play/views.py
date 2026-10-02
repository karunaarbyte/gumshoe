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
