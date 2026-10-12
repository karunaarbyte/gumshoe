"""A generated case as text a developer can read from top to bottom (it names the truth)."""

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.check.lint import phrase


def render_case(case: Case, pack: Pack) -> list[str]:
    people = {s.id: s.display_name for s in case.suspects}
    places = {loc.id: loc.name for loc in case.locations}
    methods = {m.id: m.label for m in case.methods}
    motives = {v.id: v.label for v in case.motives}
    lines = [case.intro, ""]
    lines.append(
        f"Truth: {people[case.truth.who]}; {methods[case.truth.how]}; {motives[case.truth.why]}"
    )
    lines += ["", "Suspects:"]
    for s in case.suspects:
        lines.append(f"  {s.display_name}: {'; '.join(s.traits)}. {s.style}")
    lines += ["", "Places:"]
    for loc in case.locations:
        lines.append(f"  {loc.name}: {loc.description}")
    sections: dict[str, list[str]] = {}
    for fact in case.facts:
        source = fact.source
        if source.kind is SourceKind.SEARCH:
            title = f"Search {places[source.target]}"
        elif source.kind is SourceKind.INTERROGATE:
            title = f"Question {people[source.target]}"
        else:
            about = people.get(source.subject or "") or places.get(source.subject or "") or "?"
            title = f"Read {_record(pack, source.target)} about {about}"
        mark = "" if fact.truthful else " [false]"
        entry = f"  - {fact.text}{mark}"
        if fact.contradiction:
            entry += f"\n      {fact.contradiction}"
        sections.setdefault(title, []).append(entry)
    for title in sorted(sections):
        lines += ["", f"{title}:", *sorted(sections[title])]
    return lines


def _record(pack: Pack, kind: str) -> str:
    definition = next((d for d in pack.record_defs if d.key == kind), None)
    return phrase(definition.names[0]) if definition and definition.names else kind
