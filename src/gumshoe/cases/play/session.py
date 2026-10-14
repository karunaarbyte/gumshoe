"""GameSession: the only door to a game. It keeps the skeleton Case and the PlayState
server-side and hands out views, never ids, truth or effect kinds."""

from collections.abc import Mapping
from typing import Literal

from gumshoe.cases.core.ids import make_id
from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Fact, SourceRef
from gumshoe.cases.model.enums import Axis, SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.serialize import load_case, skeleton_digest
from gumshoe.cases.play.accuse import AccuseKind, GameNotOver, give_up, score
from gumshoe.cases.play.accuse import accuse as engine_accuse
from gumshoe.cases.play.accuse import reveal as engine_reveal
from gumshoe.cases.play.engine import (
    Contradiction,
    SourceStatus,
    available_facts,
    exposer_of,
    is_open,
    is_player_source,
    record_kinds,
    source_sort_key,
    use_source,
)
from gumshoe.cases.play.labels import match_label as match_label_ids
from gumshoe.cases.play.parse import AccusationPrompt, accusation_questions
from gumshoe.cases.play.parse import interpret as interpret_answers
from gumshoe.cases.play.parse import interpret_probabilities as interpret_picks
from gumshoe.cases.play.persona import persona_brief
from gumshoe.cases.play.reply_check import reply_check
from gumshoe.cases.play.state import MAX_ATTEMPTS, PlayState, Status, Triple, new_state
from gumshoe.cases.play.views import (
    AccusationPlan,
    AccusationQuestions,
    AccusationResult,
    AxisOptions,
    AxisProblem,
    Candidate,
    ContradictionView,
    FactView,
    LocationView,
    NotebookFact,
    NotebookSection,
    NotebookView,
    ParsedAccusation,
    PersonaBrief,
    PlayerCaseView,
    QuestionView,
    RecordKindView,
    ReplyCheck,
    ReplyViolation,
    ResolvedPart,
    RevealView,
    SourceResult,
    SuspectView,
)
from gumshoe.cases.rules import gate
from gumshoe.decider import DecisionResult

FALLBACK_CONTRADICTION = 'That statement does not hold up against what you have found: "{text}"'

__all__ = [
    "FALLBACK_CONTRADICTION",
    "BadAnswers",
    "GameNotOver",
    "GameOver",
    "GameSession",
    "HandleCollision",
    "InconsistentState",
    "NoAccusationPrompt",
    "StateMismatch",
    "UnknownHandle",
    "load_session",
]


class GameOver(Exception):
    """The game has ended: no more actions."""


class HandleCollision(ValueError):
    """Two entities got the same handle under this salt; the caller draws another salt."""


class UnknownHandle(LookupError):
    """A handle that does not name what the call needs (for example a non-suspect)."""


class InconsistentState(ValueError):
    """A saved play state no game of this case could reach (a hand-edited save)."""


class StateMismatch(ValueError):
    """The play state belongs to a different case."""


class NoAccusationPrompt(LookupError):
    """`interpret_probabilities` was called with no accusation_questions call to answer."""


class BadAnswers(ValueError):
    """Answers that do not fit the stored accusation questions."""


def _humanise(key: str) -> str:
    return key.replace("_", " ")


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _check_history(ix: CaseIndex, state: PlayState) -> None:
    """Every saved accusation names candidates of this case, appears once, and carries the
    score it really has: what the accusation flow writes, and nothing else."""
    seen: set[Triple] = set()
    for record in state.accusations:
        triple = record.triple
        if any(triple.on(axis) not in ix.candidates[axis] for axis in Axis):
            raise InconsistentState("a saved accusation names something that is not a candidate")
        if triple in seen:
            raise InconsistentState("a saved accusation appears twice")
        if record.correct != score(ix, triple):
            raise InconsistentState("a saved accusation carries the wrong score")
        seen.add(triple)


def _make_handles(case: Case, salt: str) -> dict[str, str]:
    ids = [
        *(x.id for x in case.suspects),
        *(x.id for x in case.locations),
        *(x.id for x in case.methods),
        *(x.id for x in case.motives),
        *(x.id for x in case.facts),
    ]
    handles = {entity: make_id("h", salt, entity) for entity in ids}
    if len(set(handles.values())) != len(handles):
        raise HandleCollision("handle collision: use another salt")
    return handles


class GameSession:
    """With the pack the case was made from, record kinds carry the pack's display names and
    `check_reply` checks the pack's whole method and motive vocabulary. Without it (a fixture or
    an imported case), kinds are named after their keys and only the case's own candidates are
    checked."""

    def __init__(
        self, case: Case, salt: str, state: PlayState | None = None, *, pack: Pack | None = None
    ) -> None:
        if state is None:
            state = new_state(case)
        elif state.case_digest != skeleton_digest(case):
            raise StateMismatch("this save belongs to a different case")
        else:  # a hand-edited save may name facts the case does not have
            known = {f.id for f in case.facts}
            state = state.model_copy(
                update={"discovered": tuple(f for f in state.discovered if f in known)}
            )
        self._ix = CaseIndex.of(case)
        _check_history(self._ix, state)
        self._state = state
        self._handles = _make_handles(case, salt)
        self._ids = {handle: entity for entity, handle in self._handles.items()}
        self._prompt: AccusationPrompt | None = None
        self._pack = pack
        self._record_names = (
            {d.key: d.names[0].text for d in pack.record_defs if d.names} if pack else {}
        )

    # -- state ------------------------------------------------------------------------------

    @property
    def status(self) -> str:
        return self._state.status.value

    @property
    def attempts_left(self) -> int:
        return MAX_ATTEMPTS - self._state.attempts

    def state_json(self) -> str:
        """The save, for the player's own device or the server's store. It is spoiler-bearing
        (raw fact and candidate ids, the accusations tried): never hand it to an agent tool."""
        return self._state.model_dump_json()

    def give_up(self) -> None:
        self._require_playing()
        self._state = give_up(self._state)

    def _require_playing(self) -> None:
        if self._state.status is not Status.PLAYING:
            raise GameOver("the game has ended")

    # -- names and labels -------------------------------------------------------------------

    def _suspect_name(self, suspect_id: str) -> str:
        s = self._ix.suspects[suspect_id]
        return s.display_name or s.label

    def _location_name(self, location_id: str) -> str:
        loc = self._ix.locations[location_id]
        return loc.name or loc.kind

    def _record_name(self, kind: str) -> str:
        return self._record_names.get(kind) or _humanise(kind)

    def _subject_name(self, subject: str) -> str:
        if subject in self._ix.suspects:
            return self._suspect_name(subject)
        if subject in self._ix.locations:
            return self._location_name(subject)
        return "something"  # unreachable for followable sources; never an event's action

    def _label(self, source: SourceRef) -> str:
        if source.kind is SourceKind.SEARCH:
            return self._location_name(source.target)
        if source.kind is SourceKind.INTERROGATE:
            return self._suspect_name(source.target)
        subject = self._subject_name(source.subject or "")
        return f"{_capital(self._record_name(source.target))}: {subject}"

    # -- views ------------------------------------------------------------------------------

    def _fact_view(self, fact: Fact, exposed: frozenset[str]) -> FactView:
        speaker = fact.speaker if fact.speaker in self._ix.suspects else None
        return FactView(
            handle=self._handles[fact.id],
            text=fact.text,
            speaker=self._suspect_name(speaker) if speaker else None,
            source=self._label(fact.source),
            contradicted=fact.id in exposed,
        )

    def _contradiction_view(self, item: Contradiction) -> ContradictionView:
        lie = self._ix.facts[item.lie]
        return ContradictionView(
            lie=self._handles[item.lie],
            exposer=self._handles[item.exposer],
            text=lie.contradiction or FALLBACK_CONTRADICTION.format(text=lie.text),
        )

    def brief(self) -> PlayerCaseView:
        held = self._state.held
        case = self._ix.case
        locations = sorted(case.locations, key=lambda x: (self._location_name(x.id), x.id))
        suspects = sorted(case.suspects, key=lambda x: (self._suspect_name(x.id), x.id))
        return PlayerCaseView(
            intro=case.intro,
            locations=tuple(
                LocationView(
                    number=n,
                    handle=self._handles[loc.id],
                    name=self._location_name(loc.id),
                    description=loc.description,
                    locked=not is_open(
                        self._ix, held, SourceRef(kind=SourceKind.SEARCH, target=loc.id)
                    ),
                )
                for n, loc in enumerate(locations, start=1)
            ),
            suspects=tuple(
                SuspectView(
                    number=n,
                    handle=self._handles[sus.id],
                    name=self._suspect_name(sus.id),
                    description=sus.description,
                    locked=not is_open(
                        self._ix, held, SourceRef(kind=SourceKind.INTERROGATE, target=sus.id)
                    ),
                )
                for n, sus in enumerate(suspects, start=1)
            ),
            record_kinds=tuple(
                RecordKindView(key=k, label=self._record_name(k)) for k in record_kinds(self._ix)
            ),
            attempts_left=self.attempts_left,
            status=self.status,
        )

    # -- using sources ----------------------------------------------------------------------

    def _result(
        self,
        kind: Literal["search", "interrogate", "records"],
        label: str,
        status: str,
        new_ids: tuple[str, ...] = (),
        contradictions: tuple[Contradiction, ...] = (),
        opened: tuple[SourceRef, ...] = (),
        kinds: tuple[str, ...] = (),
    ) -> SourceResult:
        exposed = gate.exposed(self._ix, self._state.held)
        return SourceResult(
            kind=kind,
            label=label,
            status=status,
            new_facts=tuple(self._fact_view(self._ix.facts[i], exposed) for i in sorted(new_ids)),
            contradictions=tuple(self._contradiction_view(c) for c in contradictions),
            opened=tuple(self._label(s) for s in opened if is_player_source(self._ix, s)),
            kinds=kinds,
        )

    def _single(
        self, kind: Literal["search", "interrogate"], source_kind: SourceKind, handle: str
    ) -> SourceResult:
        self._require_playing()
        target = self._ids.get(handle, "")
        known = self._ix.locations if source_kind is SourceKind.SEARCH else self._ix.suspects
        if target not in known:
            return self._result(kind, "", SourceStatus.UNKNOWN.value)
        source = SourceRef(kind=source_kind, target=target)
        label = self._label(source)
        self._state, out = use_source(self._ix, self._state, source)
        return self._result(
            kind, label, out.status.value, out.new_facts, out.contradictions, out.opened
        )

    def search(self, location_handle: str) -> SourceResult:
        return self._single("search", SourceKind.SEARCH, location_handle)

    def interrogate(self, suspect_handle: str) -> SourceResult:
        return self._single("interrogate", SourceKind.INTERROGATE, suspect_handle)

    def check_records(self, subject_handle: str, kind: str | None = None) -> SourceResult:
        """Records about a suspect or a location: one kind, or every kind declared about them."""
        self._require_playing()
        subject = self._ids.get(subject_handle, "")
        if subject not in self._ix.suspects and subject not in self._ix.locations:
            return self._result("records", "", SourceStatus.UNKNOWN.value)
        if kind is not None and kind not in record_kinds(self._ix):
            return self._result("records", "", SourceStatus.UNKNOWN.value)
        wanted = (
            (kind,)
            if kind is not None
            else tuple(
                sorted({r.kind for r in self._ix.case.record_sources if r.subject == subject})
            )
        )
        name = self._subject_name(subject)
        label = f"{_capital(self._record_name(kind))}: {name}" if kind else f"Records: {name}"
        statuses: list[SourceStatus] = []
        new_ids: list[str] = []
        contradictions: list[Contradiction] = []
        opened: set[SourceRef] = set()
        contributed: list[str] = []
        for k in wanted:
            source = SourceRef(kind=SourceKind.RECORD, target=k, subject=subject)
            self._state, out = use_source(self._ix, self._state, source)
            statuses.append(out.status)
            new_ids += out.new_facts
            contradictions += out.contradictions
            opened |= set(out.opened)
            if out.status is SourceStatus.OK:
                contributed.append(self._record_name(k))
        # a kind read later in this call may have exhausted a source an earlier kind opened
        still_open = {s for s in opened if available_facts(self._ix, self._state.held, s)}
        if SourceStatus.OK in statuses:
            status = SourceStatus.OK
        elif SourceStatus.LOCKED in statuses:
            status = SourceStatus.LOCKED
        else:
            status = SourceStatus.NOTHING_NEW
        return self._result(
            "records",
            label,
            status.value,
            tuple(new_ids),
            tuple(contradictions),
            tuple(sorted(still_open, key=source_sort_key)),
            tuple(contributed),
        )

    # -- the notebook -----------------------------------------------------------------------

    def notebook(self) -> NotebookView:
        ix, held = self._ix, self._state.held
        exposed = gate.exposed(ix, held)
        groups: dict[SourceRef, list[Fact]] = {}
        for fact in ix.case.facts:
            if fact.id in held:
                groups.setdefault(fact.source, []).append(fact)

        def relates(fact: Fact) -> tuple[str, ...]:
            names = {
                self._suspect_name(e.candidate)
                for e in fact.effects
                if e.axis is Axis.WHO and e.candidate in ix.suspects
            }
            return tuple(sorted(names))

        sections = tuple(
            NotebookSection(
                source=self._label(source),
                facts=tuple(
                    NotebookFact(
                        handle=self._handles[f.id],
                        text=f.text,
                        speaker=self._suspect_name(f.speaker) if f.speaker in ix.suspects else None,
                        relates_to=relates(f),
                        contradicted=f.id in exposed,
                    )
                    for f in facts
                ),
            )
            for source, facts in sorted(
                groups.items(), key=lambda kv: (self._label(kv[0]), source_sort_key(kv[0]))
            )
        )
        contradictions = tuple(
            self._contradiction_view(Contradiction(lie=lie, exposer=exposer_of(ix, lie, held)))
            for lie in sorted(exposed)
        )
        return NotebookView(sections=sections, contradictions=contradictions)

    # -- accusation -------------------------------------------------------------------------

    def _candidate_name(self, axis: Axis, candidate: str) -> str:
        if axis is Axis.WHO:
            return self._suspect_name(candidate)
        if axis is Axis.HOW:
            return self._ix.methods[candidate].label
        return self._ix.motives[candidate].label

    def nameable(self, axis: str) -> AxisOptions:
        """The candidates the gate lets the player name right now, with a warning flag."""
        ax = Axis(axis)
        held = self._state.held
        options = []
        for candidate in self._ix.candidates[ax]:
            permission = gate.permission(self._ix, held, ax, candidate)
            if permission.allowed:
                options.append(
                    Candidate(
                        handle=self._handles[candidate],
                        name=self._candidate_name(ax, candidate),
                        warned=permission.warn,
                    )
                )
        options.sort(key=lambda c: (c.name, c.handle))
        return AxisOptions(axis=axis, options=tuple(options))

    def _visible(self, axis: Axis, handle: str | None) -> str | None:
        """How and why candidates the gate has not opened look exactly like non-candidates,
        so their existence cannot be probed. Suspects are public and pass through."""
        if handle is None or self._ids.get(handle) not in self._namable_ids(axis):
            return None
        return handle

    def _namable_ids(self, axis: Axis) -> frozenset[str]:
        """Candidates a typed or asked-about name may resolve to: every suspect (they are public)
        and the how and why candidates the gate has opened."""
        return frozenset(
            c
            for c in self._ix.candidates[axis]
            if axis is Axis.WHO or gate.permission(self._ix, self._state.held, axis, c).allowed
        )

    def match_label(self, axis: str, text: str) -> str | None:
        """Typed-text path: the handle of the one candidate the text names, else None (also for
        a how or why candidate the player may not name yet)."""
        ax = Axis(axis)
        found = match_label_ids(self._ix, ax, text, self._namable_ids(ax))
        return None if found is None else self._handles[found]

    def accusation_prompt(self, player_text: str) -> AccusationPrompt:
        return accusation_questions(
            self._ix,
            self._handles.__getitem__,
            len(self._state.accusations),
            player_text,
            {axis: self._namable_ids(axis) for axis in Axis},
        )

    def interpret(self, prompt: AccusationPrompt, result: DecisionResult) -> ParsedAccusation:
        picks = {
            axis: self._visible(axis, h) for axis, h in interpret_answers(prompt, result).items()
        }
        return ParsedAccusation(who=picks[Axis.WHO], how=picks[Axis.HOW], why=picks[Axis.WHY])

    def accusation_questions(self, player_text: str) -> AccusationQuestions:
        """The questions for a decision model, as plain views. The letter-to-handle keys stay
        here: the prompt is stored (replacing any earlier one) for `interpret_probabilities`."""
        prompt = self.accusation_prompt(player_text)
        self._prompt = prompt
        return AccusationQuestions(
            state=prompt.state,
            questions={
                axis: QuestionView(instructions=q.instructions, criteria=dict(q.criteria))
                for axis, q in prompt.questions.items()
            },
        )

    def interpret_probabilities(
        self, probabilities: Mapping[str, Mapping[str, float]]
    ) -> ParsedAccusation:
        """Apply the engine's confidence rule to option probabilities (axis -> letter -> p) for
        the stored questions; the stored prompt is then used up."""
        prompt = self._prompt
        if prompt is None:
            raise NoAccusationPrompt("no accusation questions are waiting for answers")
        for axis, picks in probabilities.items():
            keymap = prompt.keys.get(axis)
            if keymap is None:
                raise BadAnswers(f"no question was asked for {axis!r}")
            for letter, p in picks.items():
                if letter not in keymap:
                    raise BadAnswers(f"{letter!r} is not an option for {axis!r}")
                if not 0.0 <= p <= 1.0:  # also false for NaN
                    raise BadAnswers("a probability must be between 0 and 1")
        self._prompt = None
        picks_by_axis = {
            axis: self._visible(axis, h)
            for axis, h in interpret_picks(prompt, probabilities).items()
        }
        return ParsedAccusation(
            who=picks_by_axis[Axis.WHO], how=picks_by_axis[Axis.HOW], why=picks_by_axis[Axis.WHY]
        )

    def _candidate_id(self, axis: Axis, handle: str | None) -> str | None:
        candidate = self._ids.get(handle or "")
        return candidate if candidate in self._ix.candidates[axis] else None

    def _triple(self, parsed: ParsedAccusation) -> Triple | None:
        who = self._candidate_id(Axis.WHO, parsed.who)
        how = self._candidate_id(Axis.HOW, parsed.how)
        why = self._candidate_id(Axis.WHY, parsed.why)
        if who is None or how is None or why is None:
            return None
        return Triple(who=who, how=how, why=why)

    def describe_accusation(self, parsed: ParsedAccusation) -> AccusationPlan:
        """Resolve what was said into names, say what is missing or not yet allowed (and what
        may be named instead), collect soft warnings, and build the one confirmation line."""
        held = self._state.held
        resolved: list[ResolvedPart] = []
        problems: list[AxisProblem] = []
        warnings: list[str] = []
        ids: dict[Axis, str] = {}
        for axis in Axis:
            candidate = self._candidate_id(axis, getattr(parsed, axis.value))
            if candidate is None:
                problems.append(
                    AxisProblem(
                        axis=axis.value,
                        reason="unclear",
                        options=self.nameable(axis.value).options,
                    )
                )
                continue
            permission = gate.permission(self._ix, held, axis, candidate)
            if not permission.allowed:
                # a hidden how/why candidate must look like no answer at all (no probing)
                problems.append(
                    AxisProblem(
                        axis=axis.value,
                        reason="not_permitted" if axis is Axis.WHO else "unclear",
                        options=self.nameable(axis.value).options,
                    )
                )
                continue
            name = self._candidate_name(axis, candidate)
            ids[axis] = candidate
            resolved.append(ResolvedPart(axis=axis.value, name=name))
            if permission.warn:
                warnings.append(
                    f"You hold an alibi or clue against {name}. Name them anyway?"
                    if axis is Axis.WHO
                    else f'You hold a clue against "{name}". Name it anyway?'
                )
        repeat = False
        if len(ids) == len(Axis):
            triple = Triple(who=ids[Axis.WHO], how=ids[Axis.HOW], why=ids[Axis.WHY])
            repeat = any(r.triple == triple for r in self._state.accusations)
        can_confirm = not problems and not repeat and self._state.status is Status.PLAYING
        confirmation = (
            f"Your accusation: {' / '.join(p.name for p in resolved)}. "
            f"This uses one of your {self.attempts_left} remaining attempts. Confirm?"
            if can_confirm
            else ""
        )
        return AccusationPlan(
            resolved=tuple(resolved),
            problems=tuple(problems),
            warnings=tuple(warnings),
            repeat=repeat,
            can_confirm=can_confirm,
            confirmation=confirmation,
        )

    def _answer(self, status: str, message: str, correct: int | None = None) -> AccusationResult:
        return AccusationResult(
            status=status,
            correct=correct,
            attempts_left=self.attempts_left,
            game=self.status,
            message=message,
        )

    def accuse(self, parsed: ParsedAccusation, *, confirmed: bool = False) -> AccusationResult:
        """Rechecks the gate and the repeat rule now; only a confirmed, permitted, new triple
        consumes an attempt, and the answer is a count and nothing else."""
        self._require_playing()
        triple = self._triple(parsed)
        held = self._state.held
        if triple is None or any(
            not gate.permission(self._ix, held, axis, triple.on(axis)).allowed
            for axis in (Axis.HOW, Axis.WHY)
        ):  # a hidden how/why candidate gets the very answer an unknown handle gets
            return self._answer("not_permitted", "Name one candidate for who, how and why.")
        self._state, result = engine_accuse(self._ix, self._state, triple, confirmed=confirmed)
        if result.kind is AccuseKind.NOT_PERMITTED:
            return self._answer("not_permitted", "You cannot name that yet.")
        if result.kind is AccuseKind.REPEAT:
            return self._answer("repeat", "You already tried that. It cost nothing.")
        if result.kind is AccuseKind.NEEDS_CONFIRMATION:
            return self._answer("needs_confirmation", "Please confirm your accusation.")
        correct = result.correct or 0
        message = f"{correct} of {len(Axis)} right."
        if self._state.status is Status.WON:
            message += " You solved the case!"
        elif self._state.status is Status.LOST:
            message += " That was your last attempt. The case goes cold."
        return self._answer("resolved", message, correct)

    def check_reply(self, suspect_handle: str, player_text: str, reply: str) -> ReplyCheck:
        suspect = self._ids.get(suspect_handle, "")
        if suspect not in self._ix.suspects:
            return ReplyCheck(
                ok=False, violations=(ReplyViolation(category="unknown_suspect", count=1),)
            )
        return reply_check(self._ix, self._state, suspect, player_text, reply, self._pack)

    def persona_brief(self, suspect_handle: str) -> PersonaBrief:
        suspect = self._ids.get(suspect_handle, "")
        if suspect not in self._ix.suspects:
            raise UnknownHandle("no such suspect")
        return persona_brief(self._ix, self._state, suspect, self._suspect_name(suspect))

    def reveal(self) -> RevealView:
        truth = engine_reveal(self._ix, self._state)  # raises GameNotOver while playing
        culprit = self._ix.suspects[truth.who]
        return RevealView(
            culprit=self._suspect_name(truth.who),
            method=self._ix.methods[truth.how].label,
            motive=self._ix.motives[truth.why].label,
            secret=culprit.secret_text,
        )


def load_session(
    data: bytes, salt: str, state_json: str | None = None, *, pack: Pack | None = None
) -> GameSession:
    """Build a session from case JSON bytes (and optionally a saved PlayState JSON and the pack
    the case was made from)."""
    state = PlayState.model_validate_json(state_json) if state_json is not None else None
    return GameSession(load_case(data), salt, state, pack=pack)
