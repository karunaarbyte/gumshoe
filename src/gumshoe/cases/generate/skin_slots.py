"""The values a template's placeholders take in one case, found from the case and the pack.

Both the skin stage (which fills the placeholders) and `skin_lint` (which checks the text still
holds them) read their values from here, so the two cannot drift."""

from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Location, Suspect
from gumshoe.cases.model.pack import Entry, Pack
from gumshoe.cases.packs.check.lint import POSSESSIVE, phrase


def name_entry(pack: Pack, suspect: Suspect) -> Entry:
    """The pool entry the roster named the suspect from (its text is the first alias)."""
    role = next((r for r in pack.roles if r.key == suspect.role), None)
    entry = next((e for e in role.names if e.text in suspect.aliases), None) if role else None
    if entry is None:
        raise GenerationError(f"suspect {suspect.id} has no name entry in the pack")
    return entry


def place_entry(pack: Pack, location: Location) -> Entry:
    """The pool entry a location was named from; before it has a name, the kind's first entry."""
    definition = next((d for d in pack.location_defs if d.key == location.kind), None)
    if definition is None or not definition.names:
        raise GenerationError(f"location kind {location.kind!r} has no names in the pack")
    return next((e for e in definition.names if e.text == location.name), definition.names[0])


def person(entry: Entry, prefix: str = "who") -> dict[str, str]:
    subject = entry.pronoun or "they"
    return {
        prefix: phrase(entry),
        f"{prefix}.subj": subject,
        f"{prefix}.poss": POSSESSIVE[subject],
    }


def place(entry: Entry) -> dict[str, str]:
    return {"place": phrase(entry), "place.in": f"in {phrase(entry)}"}


def slot_time(pack: Pack, slot: int) -> dict[str, str]:
    if slot >= len(pack.slot_defs):
        raise GenerationError(f"time slot {slot} is not defined in the pack")
    defined = pack.slot_defs[slot]
    return {"time.phrase": defined.at, "time.at": defined.at, "time.during": defined.during}


def record_name(pack: Pack, kind: str) -> dict[str, str]:
    definition = next((d for d in pack.record_defs if d.key == kind), None)
    if definition is None or not definition.names:
        raise GenerationError(f"record kind {kind!r} has no display name in the pack")
    return {"record": phrase(definition.names[0])}


def crime_event(case: Case) -> tuple[Location, int]:
    """The place and slot of the crime."""
    event = next((e for e in case.timeline if e.action == "crime"), None)
    location = next((loc for loc in case.locations if event and loc.id == event.place), None)
    if event is None or location is None:
        raise GenerationError("the case has no crime event at a known location")
    return location, event.slot
