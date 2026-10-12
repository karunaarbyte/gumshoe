"""The template skin stage: every text field of the case, rendered from the pack's wording.

The skin reads what a fact means from its structure (kind, source, effects, claim), because the
final ids are hashes and say nothing. The family of a fact may depend on its meaning; which
variant it gets, and in which order, never does: each family's variants are shuffled once on the
stage stream and dealt in fact-id order, so a case does not repeat a frame until the list ends.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence

from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact, Location, Suspect
from gumshoe.cases.model.enums import Axis, EffectKind, FactKind, SourceKind
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs.check.lint import render


class _Deal:
    """Variants dealt without repeating until the list is used up."""

    def __init__(self, stream: Stream) -> None:
        self._stream = stream
        self._lists: dict[str, list[str]] = {}
        self._used: dict[str, int] = {}

    def next(self, key: str, variants: Sequence[str]) -> str:
        if not variants:
            raise GenerationError(f"the pack has no text for {key}")
        if key not in self._lists:
            self._lists[key] = self._stream.child(f"deal/{key}").shuffle(variants)
        position = self._used.get(key, 0)
        self._used[key] = position + 1
        return self._lists[key][position % len(self._lists[key])]


def _only[T](items: Iterable[T], keep: Callable[[T], bool], what: str) -> T:
    """The first item that fits, or a `GenerationError` naming what is missing."""
    found = next((item for item in items if keep(item)), None)
    if found is None:
        raise GenerationError(f"there is no {what}")
    return found


def _family(pack: Pack, kind: str) -> tuple[str, ...]:
    """The variants of every family of this kind, in id order."""
    return tuple(v for f in pack.families if f.kind == kind for v in f.variants)


class _Skin:
    def __init__(self, ctx: GenContext, stream: Stream, case: Case) -> None:
        self.pack, self.stream, self.case = ctx.pack, stream, case
        self.deal = _Deal(stream)
        self.suspects = {s.id: s for s in case.suspects}
        self.locations = {loc.id: loc for loc in case.locations}
        self.facts = {f.id: f for f in case.facts}
        self.methods = {m.id: m for m in case.methods}
        self.motives = {v.id: v for v in case.motives}
        self.named: dict[str, Location] = {}

    # --- the people and places -------------------------------------------------------------

    def _location(self, location: Location) -> Location:
        definition = _only(
            self.pack.location_defs,
            lambda d: d.key == location.kind,
            f"location kind {location.kind!r}",
        )
        if not definition.names or not definition.descriptions:
            raise GenerationError(f"location kind {location.kind!r} has no names or descriptions")
        label = f"loc/{location.id}"
        name = self.stream.rank([e.text for e in definition.names], label)[0]
        template = self.stream.rank(list(definition.descriptions), label)[0]
        named = location.model_copy(update={"name": name})
        values = slots.place(slots.place_entry(self.pack, named))
        return named.model_copy(update={"description": render(template, values)})

    def _who(self, suspect_id: str | None) -> dict[str, str]:
        suspect = self.suspects.get(suspect_id or "")
        if suspect is None:
            raise GenerationError(
                f"a text needs the suspect {suspect_id!r}, who is not in the case"
            )
        return slots.person(slots.name_entry(self.pack, suspect))

    def _place(self, location_id: str) -> dict[str, str]:
        location = self.named.get(location_id)
        if location is None:
            raise GenerationError(f"a text needs the location {location_id!r}, which is not named")
        return slots.place(slots.place_entry(self.pack, location))

    # --- one fact --------------------------------------------------------------------------

    def _effect(self, fact: Fact, axis: Axis) -> tuple[str, EffectKind]:
        found = [e for e in fact.effects if e.axis is axis]
        if len(found) != 1:
            raise GenerationError(f"fact {fact.id} should have one {axis.value} effect")
        return found[0].candidate, found[0].kind

    @staticmethod
    def _known[T](items: Mapping[str, T], ident: str, what: str) -> T:
        if ident not in items:
            raise GenerationError(f"a fact names the {what} {ident!r}, who is not in the case")
        return items[ident]

    def _method(self, fact: Fact) -> str:
        return self._known(self.methods, self._effect(fact, Axis.HOW)[0], "method").type

    def _motive(self, fact: Fact) -> str:
        return self._known(self.motives, self._effect(fact, Axis.WHY)[0], "motive").type

    def _text(self, fact: Fact) -> str:
        pack, kind = self.pack, fact.kind
        record = (
            slots.record_name(pack, fact.source.target)
            if fact.source.kind is SourceKind.RECORD
            else {}
        )
        if kind is FactKind.SECRET:
            key = self._motive(fact)
            motive = _only(pack.motive_defs, lambda d: d.key == key, f"motive {key!r}")
            subject = fact.source.subject
            return render(
                self.deal.next(f"secrets/{motive.key}", motive.secrets), self._who(subject)
            )
        if kind in (FactKind.PRESENCE, FactKind.ALIBI) and fact.claim is not None:
            values = {
                **self._who(fact.claim.actor),
                **self._place(fact.claim.place or ""),
                **slots.slot_time(pack, fact.claim.slot),
                **record,
            }
            return render(self.deal.next("presence_record", _family(pack, "record")), values)
        if kind is FactKind.PHYSICAL:
            proof = self._effect(fact, Axis.WHO)[1] is EffectKind.PROVES
            family = "physical_proof" if proof else "physical_clear"
            values = {**self._who(fact.source.subject), **record}
            return render(self.deal.next(family, _family(pack, family)), values)
        if kind is FactKind.MOTIVE_CLUE:
            key = self._motive(fact)
            motive = _only(pack.motive_defs, lambda d: d.key == key, f"motive {key!r}")
            return render(
                self.deal.next(f"hints/{motive.key}", motive.hints), self._who(fact.speaker)
            )
        if kind is FactKind.LIE and fact.claim is not None and fact.exposure_hook is not None:
            values = {
                **self._who(fact.claim.actor),
                **self._place(fact.claim.place or ""),
                **slots.slot_time(pack, fact.claim.slot),
                **slots.record_name(pack, fact.exposure_hook.target),
            }
            return render(self.deal.next("lie", _family(pack, "lie")), values)
        if kind in (FactKind.TRACE, FactKind.ABSENT_TRACE):
            key = self._method(fact)
            method = _only(pack.method_defs, lambda d: d.key == key, f"method {key!r}")
            trace = next((t for t in method.traces if t.kind == fact.trace_kind), None)
            if trace is None:
                raise GenerationError(f"method {method.key!r} has no trace {fact.trace_kind!r}")
            texts = trace.templates if kind is FactKind.TRACE else trace.absent
            key = f"{'traces' if kind is FactKind.TRACE else 'absent'}/{method.key}/{trace.kind}"
            return render(self.deal.next(key, texts), self._place(fact.source.target))
        if kind is FactKind.CLUE:
            if fact.source.kind is SourceKind.RECORD:
                definition = _only(
                    pack.record_defs, lambda d: d.key == fact.source.target, "record kind"
                )
                return render(
                    self.deal.next(f"entries/{definition.key}", definition.entries), record
                )
            if fact.effects:
                key = self._method(fact)
                method = _only(pack.method_defs, lambda d: d.key == key, f"method {key!r}")
                return render(
                    self.deal.next(f"clues/{method.key}", method.clues),
                    self._place(fact.source.target),
                )
            holder = next((s for s in self.case.suspects if fact.id in s.requires), None)
            return render(
                self.deal.next("key", _family(pack, "key")),
                self._who(holder.id if holder else None),
            )
        raise GenerationError(f"the skin has no text for fact {fact.id} ({kind.value})")

    def _contradiction(self, fact: Fact) -> str | None:
        if fact.kind is not FactKind.LIE:
            return None
        exposer = self.facts.get(fact.exposed_by[0]) if fact.exposed_by else None
        if exposer is None or exposer.claim is None or fact.claim is None:
            raise GenerationError(f"lie {fact.id} has no exposer with a claim")
        values = {
            **self._who(fact.claim.actor),
            **self._place(exposer.claim.place or ""),
            **slots.slot_time(self.pack, exposer.claim.slot),
            **slots.record_name(self.pack, exposer.source.target),
        }
        return render(self.deal.next("contradiction", _family(self.pack, "contradiction")), values)

    # --- the case --------------------------------------------------------------------------

    def run(self) -> Case:
        pack, case = self.pack, self.case
        self.named = {loc.id: self._location(loc) for loc in case.locations}
        ordered = sorted(case.facts, key=lambda f: f.id)
        texts = {f.id: self._text(f) for f in ordered}
        contradictions = {f.id: self._contradiction(f) for f in ordered}
        facts = tuple(
            f.model_copy(update={"text": texts[f.id], "contradiction": contradictions[f.id]})
            for f in case.facts
        )
        scene, slot = slots.crime_event(case)
        if not pack.victims:
            raise GenerationError("the pack has no victims")
        chosen = self.stream.rank([v.text for v in pack.victims], "victim")[0]
        victim_entry = _only(pack.victims, lambda v: v.text == chosen, "victim")
        intro_values = {
            **slots.person(victim_entry, "victim"),
            **slots.place(slots.place_entry(pack, self.named[scene.id])),
            **slots.slot_time(pack, slot),
        }
        intro = render(self.deal.next("intro", _family(pack, "intro")), intro_values)
        suspects = tuple(self._suspect(s, texts) for s in case.suspects)
        return case.model_copy(
            update={
                "facts": facts,
                "suspects": suspects,
                "locations": tuple(self.named[loc.id] for loc in case.locations),
                "intro": intro,
                "smalltalk_allow": pack.smalltalk_allow,
            }
        )

    def _suspect(self, suspect: Suspect, texts: Mapping[str, str]) -> Suspect:
        role = _only(self.pack.roles, lambda r: r.key == suspect.role, f"role {suspect.role!r}")
        return suspect.model_copy(
            update={
                "display_name": suspect.label,
                "traits": role.traits,
                "style": role.style,
                "secret_text": self._known(texts, suspect.secret_fact, "secret fact"),
            }
        )


def template_skin(ctx: GenContext, stream: Stream, case: Case) -> Case:
    """The case with every skin field filled from the pack's templates. Skeleton fields are
    untouched. `skin_rev` and `skin_hash` are stamped by the pipeline."""
    return _Skin(ctx, stream, case).run()
