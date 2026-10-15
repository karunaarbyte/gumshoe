"""take_turn: the only place the stages meet. One call of `take_turn` is one player message."""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel

from gumshoe.agent import accuse as accusation
from gumshoe.agent import guidance
from gumshoe.agent.deps import Deps, TurnContext
from gumshoe.agent.dialogue import draft_reply, evidence_against, post_check
from gumshoe.agent.events import (
    Cancelled,
    Clarify,
    Confirm,
    Done,
    GameOver,
    IntentEvent,
    Reply,
    ToolCall,
    ToolResult,
    TurnEvent,
)
from gumshoe.agent.game import INTERNAL, ToolFailure
from gumshoe.agent.pending import Pending, Step, is_actionable, resolve_pending
from gumshoe.agent.state import build_state
from gumshoe.agent.understand import Intent, build_understand, read_intent
from gumshoe.cases import NotebookView, ParsedAccusation, PlayerCaseView
from gumshoe.decider import DeciderError, describe_failure

logger = logging.getLogger(__name__)

APOLOGY = "I lost my train of thought. Could you say that again?"
UNREACHABLE = (
    "You haven't found a way to them yet. Keep digging: searching, questioning and reading "
    "records turn up new people."
)
NOTHING_PENDING = "There is nothing waiting for your confirmation right now."
YES_WORDS = frozenset(
    {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "go ahead", "do it"}
)
MAX_EXCHANGES = 20
NEEDS_TARGET = frozenset({"search", "interrogate", "talk", "records"})


def ended(ctx: TurnContext, brief: PlayerCaseView) -> Literal["won", "lost", "gave_up"]:
    """How a finished game ended: what a turn reported, else the engine's status."""
    if ctx.outcome is not None:
        return ctx.outcome
    return "won" if brief.status == "won" else "lost"


def is_bare_yes(text: str) -> bool:
    """A message that is only a yes ("Yes!", "ok", "go ahead"), whatever the case or marks."""
    return " ".join(re.findall(r"[a-z]+", text.lower())) in YES_WORDS


def _remember(ctx: TurnContext, text: str, summary: str) -> None:
    ctx.unclear = 0  # a message we understood ends a run of ones we did not
    ctx.exchanges.append((text, summary))
    del ctx.exchanges[:-MAX_EXCHANGES]


async def _tool[T: BaseModel](
    name: str, args: dict[str, Any], call: Callable[[], Awaitable[T]]
) -> tuple[list[TurnEvent], T | None, ToolFailure | None]:
    """Run a tool the player can see: its call and result become events. A refusal (bad handle,
    or game_over) is a failed result. A vanished game or a server bug is returned as `fatal`: the
    caller yields the events (the call stays visible), then raises it. `game_over` is a failed
    result, not fatal: step 0 of `_turn` answers a finished game, so under the per-game lock it
    cannot appear mid-turn."""
    events: list[TurnEvent] = [ToolCall(tool=name, args=args)]
    try:
        result = await call()
    except ToolFailure as exc:
        if exc.code in ("unknown_game", INTERNAL):
            return events, None, exc
        events.append(ToolResult(tool=name, ok=False, code=exc.code, message=exc.message))
        return events, None, None
    events.append(ToolResult(tool=name, ok=True, data=result.model_dump(mode="json")))
    return events, result, None


def confirm_event(pending: Pending, decision_id: str | None = None) -> Confirm:
    return Confirm(
        pending=pending.kind,
        pending_id=pending.id,
        text=pending.line,
        warnings=pending.warnings,
        decision_id=decision_id,
    )


async def take_turn(
    deps: Deps, ctx: TurnContext, text: str, *, pending_id: str | None = None
) -> AsyncIterator[TurnEvent]:
    """Yield the events of one turn, always ending with `Done`. No Exception raises out of here
    (CancelledError and other BaseExceptions propagate by design). `pending_id` is the id of the
    confirmation the player had in front of them, if any: only then can a yes run it."""
    async for event in _guarded(deps, ctx, _turn(deps, ctx, text, pending_id)):
        yield event


async def take_confirm(
    deps: Deps, ctx: TurnContext, pending_id: str, answer: Literal["yes", "no"]
) -> AsyncIterator[TurnEvent]:
    """The confirm button: run or cancel the stored pending action. Deterministic: no decision is
    asked for. The API checks `pending_id` before it starts (409 otherwise); if the action has
    changed by the time this runs, the turn says there is nothing to confirm and does nothing."""
    async for event in _guarded(deps, ctx, _confirm(deps, ctx, pending_id, answer)):
        yield event


async def _guarded(
    deps: Deps, ctx: TurnContext, events: AsyncIterator[TurnEvent]
) -> AsyncIterator[TurnEvent]:
    """Every turn's frame: remember how the game ended, turn failures into the apology, end
    with `Done`, and stop a turn that outlives `turn_timeout_s` (a safety net: the stages have
    their own timeouts). The deadline is absolute, so time a slow reader spends in a `yield`
    still counts against it, but the reader is never cancelled mid-yield. Known limit: an
    irreversible action (accuse, give up) that completes right as the net fires is reported as
    failed; the tool calls are in-process and near-instant."""
    started = time.perf_counter()
    deadline = asyncio.get_running_loop().time() + deps.config.turn_timeout_s
    budget: asyncio.Timeout | None = None
    try:
        while True:
            budget = asyncio.timeout_at(deadline)
            try:
                async with budget:
                    event = await anext(events)
            except StopAsyncIteration:
                break
            if isinstance(event, GameOver):
                ctx.outcome = event.outcome
            yield event
    except TimeoutError as exc:
        if budget is not None and budget.expired():
            logger.warning("a turn ran out of time after %s s", deps.config.turn_timeout_s)
        else:
            logger.error("turn failed: %s", describe_failure(exc))
        yield Clarify(reason="error", text=APOLOGY)
    except ToolFailure as exc:
        if exc.code != "unknown_game":
            logger.error("turn failed: %s (%s)", describe_failure(exc), exc.code)
            yield Clarify(reason="error", text=APOLOGY)
    except Exception as exc:
        logger.error("turn failed: %s", describe_failure(exc))
        yield Clarify(reason="error", text=APOLOGY)
    yield Done(turn_ms=round((time.perf_counter() - started) * 1000, 1))


async def _turn(
    deps: Deps, ctx: TurnContext, text: str, pending_id: str | None
) -> AsyncIterator[TurnEvent]:
    game = ctx.game
    brief = await deps.client.case_brief(game)
    if brief.status != "playing":
        reveal = await deps.client.reveal(game)
        yield GameOver(outcome=ended(ctx, brief), reveal=reveal)
        return
    if ctx.pending is not None and is_bare_yes(text):
        # a lone yes next to a waiting confirmation is that confirmation's answer: no model is
        # asked, so it cannot be misread as a new request (the live run read it as an accusation)
        async for event in _answer_yes(deps, ctx, text, ctx.pending, pending_id):
            yield event
        return
    if guidance.is_help_request(text):
        # "help" is a request the game can answer itself: no model is asked, nothing is billed. A
        # waiting confirmation stays waiting: help is neither its yes nor its no
        yield Reply(speaker=None, text=guidance.full_help(brief), source="help")
        _remember(ctx, text, "asked for help")
        return
    notebook = await deps.client.notebook(game)
    built = build_understand(brief, pending=ctx.pending is not None)
    state = build_state(
        text=text,
        pending_line=ctx.pending.line if ctx.pending else None,
        exchanges=ctx.exchanges,
        brief=brief,
        notebook=notebook,
        config=deps.config,
    )
    decision_id = uuid.uuid4().hex
    try:
        result = await deps.decider.decide(
            state, built.questions, node="understand", decision_id=decision_id
        )
        intent = read_intent(result, built.targets)
    except DeciderError as exc:
        logger.warning("the understand decision failed: %s", describe_failure(exc))
        yield Clarify(reason="error", text=APOLOGY, decision_id=decision_id)
        return
    except (KeyError, TypeError):
        logger.warning("the understand decision came back malformed")
        yield Clarify(reason="error", text=APOLOGY, decision_id=decision_id)
        return
    yield IntentEvent(
        decision_id=decision_id,
        intent=intent.name,
        target=intent.target,
        confidence=intent.intent_confidence,
    )
    pending = ctx.pending
    step = resolve_pending(pending, intent, deps.config)
    if step is Step.RUN:
        assert pending is not None
        async for event in _answer_yes(deps, ctx, text, pending, pending_id):
            yield event
        return
    if step is Step.REPARSE:
        assert pending is not None
        async for event in _reparse(deps, ctx, text, pending, pending_id):
            yield event
        return
    if step in (Step.CANCEL, Step.CANCEL_PROCESS):
        ctx.pending = None
        yield Cancelled()
        if step is Step.CANCEL:
            _remember(ctx, text, "cancelled")
            return
        before = len(ctx.exchanges)
        async for event in _process(deps, ctx, text, brief, intent):
            yield event
        if len(ctx.exchanges) > before:  # one message, one exchange: fold the cancel into it
            said, summary = ctx.exchanges[-1]
            ctx.exchanges[-1] = (said, f"cancelled, then {summary}")
        else:
            _remember(ctx, text, "cancelled")
        return
    elif step in (Step.DROP_PROCESS, Step.CLEAR_PROCESS):
        ctx.pending = None
        yield Cancelled()  # a UI still showing the confirmation must learn it is gone
    elif step is Step.REASK:
        assert pending is not None
        pending.reasked = True
        yield Clarify(reason="pending", text=f"Still want to go ahead? {pending.line}")
        return
    # a yes with nothing to answer: the confirmation it meant is gone (or never existed)
    stale_yes = pending is None and (pending_id is not None or is_bare_yes(text))
    async for event in _process(deps, ctx, text, brief, intent, stale_yes=stale_yes):
        yield event


async def _confirm(
    deps: Deps, ctx: TurnContext, pending_id: str, answer: Literal["yes", "no"]
) -> AsyncIterator[TurnEvent]:
    pending = ctx.pending
    if pending is None or pending.id != pending_id:
        yield Clarify(reason="pending", text=NOTHING_PENDING)
        return
    ctx.pending = None  # cleared first, as for a typed yes
    if answer == "no":
        yield Cancelled()
        _remember(ctx, "no", "cancelled")
        return
    async for event in _run_pending(deps, ctx, "yes", pending):
        yield event


async def _process(
    deps: Deps,
    ctx: TurnContext,
    text: str,
    brief: PlayerCaseView,
    intent: Intent,
    *,
    stale_yes: bool = False,
) -> AsyncIterator[TurnEvent]:
    config = deps.config
    game = ctx.game
    if stale_yes and not is_actionable(intent, config):
        yield Reply(
            speaker=None, text=f"{NOTHING_PENDING} {guidance.short_nudge(brief)}", source="help"
        )
        _remember(ctx, text, "there was nothing to confirm")
        return
    if intent.intent_confidence < config.confidence_gate:
        ctx.unclear += 1
        if ctx.unclear >= 2:  # still lost: stop hinting and lay the moves out
            said = guidance.full_help(brief)
        elif (hint := guidance.tailored(brief, intent.name)) is not None:
            said = f"I did not catch that. {hint}"
        else:
            said = guidance.short_nudge(brief)
        yield Clarify(reason="low_confidence", text=said)
        return
    name = intent.name
    handle = intent.target
    if name in NEEDS_TARGET:
        if handle is None or intent.target_confidence < config.confidence_gate:
            ctx.unclear += 1
            yield Clarify(reason="bad_target", text=guidance.which_text(brief, name))
            return
        places = {x.handle for x in brief.locations}
        suspects = {x.handle for x in brief.suspects}
        allowed = {
            "search": places,
            "interrogate": suspects,
            "talk": suspects,
            "records": places | suspects,
        }[name]
        if handle not in allowed:
            ctx.unclear += 1
            yield Clarify(reason="mismatch", text=guidance.mismatch_text(brief, handle))
            return
    ctx.unclear = 0  # it is a move we understood, whatever it then leads to
    if name == "search" and handle is not None:
        found, searched, fatal = await _tool(
            "search", {"game": game, "location": handle}, lambda: deps.client.search(game, handle)
        )
        for event in found:
            yield event
        if fatal is not None:
            raise fatal
        if searched is None:
            _remember(ctx, text, "could not search there")
        elif searched.status == "locked":  # its name is withheld, so there is nothing to quote
            _remember(ctx, text, "tried a place that is not open yet")
        else:
            _remember(ctx, text, f"searched {searched.label}: {len(searched.new_facts)} new facts")
    elif name == "records" and handle is not None:
        found, records, fatal = await _tool(
            "check_records",
            {"game": game, "subject": handle},
            lambda: deps.client.check_records(game, handle),
        )
        for event in found:
            yield event
        if fatal is not None:
            raise fatal
        if records is None:
            _remember(ctx, text, "could not read those records")
        else:
            _remember(ctx, text, f"read records: {len(records.new_facts)} new facts")
    elif name == "notebook":
        found_nb, _, fatal = await _tool(
            "notebook", {"game": game}, lambda: deps.client.notebook(game)
        )
        for event in found_nb:
            yield event
        if fatal is not None:
            raise fatal
        _remember(ctx, text, "looked over the notebook")
    elif name == "interrogate" and handle is not None:
        found, asked, fatal = await _tool(
            "interrogate",
            {"game": game, "suspect": handle},
            lambda: deps.client.interrogate(game, handle),
        )
        for event in found:
            yield event
        if fatal is not None:
            raise fatal
        if asked is not None and asked.status in ("ok", "nothing_new"):
            try:
                async for event in _converse(deps, ctx, text, handle, intent.weight):
                    yield event
            except Exception:
                # the tool already changed state and its result is sent: memory keeps the exchange
                _remember(ctx, text, f"questioned {asked.label}: {len(asked.new_facts)} new facts")
                raise
        elif asked is None:
            _remember(ctx, text, "could not question them")
        else:
            yield Reply(speaker=None, text=UNREACHABLE, source="unreachable")
            _remember(ctx, text, "could not question them yet")
    elif name == "talk" and handle is not None:
        suspect = next(s for s in brief.suspects if s.handle == handle)
        if suspect.locked:
            yield Reply(speaker=None, text=UNREACHABLE, source="unreachable")
            _remember(ctx, text, "could not talk to them yet")
        else:
            async for event in _converse(deps, ctx, text, handle, intent.weight):
                yield event
    elif name == "give_up":
        ctx.pending = Pending(kind="give_up", line="Give up and see the answer?")
        yield confirm_event(ctx.pending)
        _remember(ctx, text, "asked to confirm giving up")
    elif name == "accuse":
        async for event in _start_accusation(deps, ctx, text, brief):
            yield event
    else:  # meta and other
        yield Reply(speaker=None, text=guidance.full_help(brief), source="help")
        _remember(ctx, text, "explained what the player can do")


async def _converse(
    deps: Deps, ctx: TurnContext, text: str, suspect: str, weight: float
) -> AsyncIterator[TurnEvent]:
    persona = await deps.client.persona_brief(ctx.game, suspect)
    notebook: NotebookView = await deps.client.notebook(ctx.game)
    evidence = evidence_against(persona.name, notebook)
    config = deps.config
    model = config.model_dramatic if weight >= config.dramatic_from else config.model_default
    talks = ctx.talks.setdefault(suspect, [])  # only this suspect's own conversation
    history = talks[len(talks) - config.exchanges_kept :] if config.exchanges_kept else []
    draft = await draft_reply(
        deps,
        game=ctx.game,
        suspect=suspect,
        persona=persona,
        player_text=text,
        history=history,
        model=model,
        evidence=evidence,
    )
    yield Reply(
        speaker=persona.name,
        text=draft.text,
        source=draft.source,
        degraded=draft.degraded,
        violations=draft.violations,
        model=draft.model,
        drafts=draft.drafts,
        latency_ms=draft.latency_ms,
    )
    talks.append((text, draft.text))
    del talks[:-MAX_EXCHANGES]
    _remember(ctx, text, draft.text)
    yield await post_check(deps, reply=draft.text, persona=persona, evidence=evidence)


async def _parse_accusation(
    deps: Deps, game: str, text: str
) -> tuple[Clarify | None, ParsedAccusation | None, str]:
    """One parse_accusation decision read through the engine. Returns (the apology, None, id) when
    the decision or its reading failed, else (None, the parsed handles, id)."""
    questions = await deps.client.accusation_questions(game, text)
    decision_id = uuid.uuid4().hex
    apology = Clarify(reason="error", text=APOLOGY, decision_id=decision_id)
    try:
        result = await deps.decider.decide(
            questions.state,
            accusation.to_choice_questions(questions),
            node="parse_accusation",
            decision_id=decision_id,
        )
    except DeciderError as exc:
        logger.warning("the parse_accusation decision failed: %s", describe_failure(exc))
        return apology, None, decision_id
    try:
        parsed = await deps.client.interpret_accusation(game, accusation.probabilities_of(result))
    except ToolFailure as exc:
        if exc.code != "bad_argument":
            raise
        return apology, None, decision_id
    return None, parsed, decision_id


async def _start_accusation(
    deps: Deps, ctx: TurnContext, text: str, brief: PlayerCaseView
) -> AsyncIterator[TurnEvent]:
    apology, parsed, decision_id = await _parse_accusation(deps, ctx.game, text)
    if parsed is None:
        assert apology is not None
        yield apology
        return
    async for event in _plan_accusation(deps, ctx, text, parsed, decision_id, brief):
        yield event


async def _plan_accusation(
    deps: Deps,
    ctx: TurnContext,
    text: str,
    parsed: ParsedAccusation,
    decision_id: str,
    brief: PlayerCaseView | None = None,
) -> AsyncIterator[TurnEvent]:
    plan = await deps.client.describe_accusation(ctx.game, parsed.who, parsed.how, parsed.why)
    if plan.repeat:
        yield Clarify(
            reason="accusation",
            text="You already tried that exact accusation.",
            decision_id=decision_id,
        )
    elif plan.can_confirm and parsed.who and parsed.how and parsed.why:
        ctx.pending = Pending(
            kind="accuse",
            line=plan.confirmation,
            handles=(parsed.who, parsed.how, parsed.why),
            warnings=plan.warnings,
        )
        yield confirm_event(ctx.pending, decision_id)
        _remember(ctx, text, "asked to confirm an accusation")
    elif plan.problems:
        named = await _named_suspect(deps, ctx, parsed, brief)
        yield Clarify(
            reason="accusation",
            text=accusation.missing_text(plan, named),
            decision_id=decision_id,
            problems=accusation.problems_of(plan, named),
        )
    else:
        yield Clarify(
            reason="accusation",
            text="That accusation cannot be made right now.",
            decision_id=decision_id,
        )


async def _named_suspect(
    deps: Deps, ctx: TurnContext, parsed: ParsedAccusation, brief: PlayerCaseView | None
) -> str | None:
    """The suspect the player named, by name, only if the board already shows that name. The turn's
    own brief is used when it has one, so the name and the plan agree on the same state."""
    if parsed.who is None:
        return None
    brief = brief if brief is not None else await deps.client.case_brief(ctx.game)
    return next((s.name for s in brief.suspects if s.handle == parsed.who and not s.locked), None)


def names_the_same(parsed: ParsedAccusation, handles: tuple[str, str, str]) -> bool:
    """True when every part the player named is the stored one (naming nothing counts)."""
    return all(
        part is None or part == stored
        for part, stored in zip((parsed.who, parsed.how, parsed.why), handles, strict=True)
    )


async def _answer_yes(
    deps: Deps, ctx: TurnContext, text: str, pending: Pending, pending_id: str | None
) -> AsyncIterator[TurnEvent]:
    """A yes runs the pending action only when it answers that very confirmation. Otherwise (a
    yes sent before the confirmation was shown, from another tab, or after it changed) the
    confirmation is shown again and nothing is spent."""
    if pending_id != pending.id:
        yield confirm_event(pending)
        return
    ctx.pending = None  # cleared first: a replay can only come back as `repeat`
    async for event in _run_pending(deps, ctx, text, pending):
        yield event


async def _reparse(
    deps: Deps, ctx: TurnContext, text: str, pending: Pending, pending_id: str | None
) -> AsyncIterator[TurnEvent]:
    """A yes next to a confident accuse while an accusation is pending. If the parse names
    nothing beyond the stored accusation it is the yes; if it names another, that one replaces
    the stored one; if the parse fails, the stored one is left as it was."""
    assert pending.handles is not None
    apology, parsed, decision_id = await _parse_accusation(deps, ctx.game, text)
    if parsed is None:
        assert apology is not None
        yield apology
        return
    if names_the_same(parsed, pending.handles):
        async for event in _answer_yes(deps, ctx, text, pending, pending_id):
            yield event
        return
    ctx.pending = None
    yield Cancelled()
    async for event in _plan_accusation(deps, ctx, text, parsed, decision_id):
        yield event


async def _run_pending(
    deps: Deps, ctx: TurnContext, text: str, pending: Pending
) -> AsyncIterator[TurnEvent]:
    game = ctx.game
    if pending.kind == "give_up":
        found, reveal, fatal = await _tool(
            "give_up", {"game": game}, lambda: deps.client.give_up(game)
        )
        for event in found:
            yield event
        if fatal is not None:
            raise fatal
        if reveal is not None:
            yield GameOver(outcome="gave_up", reveal=reveal)
            _remember(ctx, text, "gave up")
        else:
            _remember(ctx, text, "could not give up")
        return
    assert pending.handles is not None
    who, how, why = pending.handles
    found_acc, result, fatal = await _tool(
        "accuse",
        {"game": game, "who": who, "how": how, "why": why, "confirmed": True},
        lambda: deps.client.accuse(game, who, how, why, True),
    )
    for event in found_acc:
        yield event
    if fatal is not None:
        raise fatal
    if result is None:
        return
    if result.status != "resolved":
        yield Clarify(reason="accusation", text=result.message)
        return
    _remember(ctx, text, f"accused: {result.correct} of 3 parts right")
    if result.game in ("won", "lost"):
        reveal = await deps.client.reveal(game)
        yield GameOver(outcome="won" if result.game == "won" else "lost", reveal=reveal)
