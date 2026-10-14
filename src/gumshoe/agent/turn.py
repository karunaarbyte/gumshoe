"""take_turn: the only place the stages meet. One call of `take_turn` is one player message."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel

from gumshoe.agent import accuse as accusation
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
from gumshoe.agent.pending import Pending, Step, resolve_pending
from gumshoe.agent.state import build_state
from gumshoe.agent.understand import Intent, build_understand, read_intent
from gumshoe.cases import NotebookView, PlayerCaseView
from gumshoe.decider import DeciderAllFailedError, DeciderAPIError, DeciderError

logger = logging.getLogger(__name__)

APOLOGY = "I lost my train of thought. Could you say that again?"
HELP = (
    "You can search a place, question a suspect, read records, check your notebook, "
    "or make an accusation."
)
UNREACHABLE = "You cannot get to them yet."
MAX_EXCHANGES = 20
NEEDS_TARGET = frozenset({"search", "interrogate", "talk", "records"})


def describe_failure(exc: DeciderError) -> str:
    """The class and backend of a failed decision, for the log. Never the message: an API error
    quotes the response body, which may echo the state and so the player's text."""
    if isinstance(exc, DeciderAllFailedError):
        parts = ", ".join(f"{name}: {type(e).__name__}" for name, e in exc.failures.items())
        return f"all backends failed ({parts})"
    status = f" HTTP {exc.status_code}" if isinstance(exc, DeciderAPIError) else ""
    return f"{type(exc).__name__} from {exc.backend}{status}"


def ended(ctx: TurnContext, brief: PlayerCaseView) -> Literal["won", "lost", "gave_up"]:
    """How a finished game ended: what a turn reported, else the engine's status."""
    if ctx.outcome is not None:
        return ctx.outcome
    return "won" if brief.status == "won" else "lost"


def _remember(ctx: TurnContext, text: str, summary: str) -> None:
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


async def take_turn(deps: Deps, ctx: TurnContext, text: str) -> AsyncIterator[TurnEvent]:
    """Yield the events of one turn, always ending with `Done`. No Exception raises out of here
    (CancelledError and other BaseExceptions propagate by design)."""
    started = time.perf_counter()
    try:
        async for event in _turn(deps, ctx, text):
            if isinstance(event, GameOver):
                ctx.outcome = event.outcome
            yield event
    except ToolFailure as exc:
        if exc.code != "unknown_game":
            logger.error("turn failed: %s", exc)
            yield Clarify(reason="error", text=APOLOGY)
    except Exception:
        logger.exception("turn failed")
        yield Clarify(reason="error", text=APOLOGY)
    yield Done(turn_ms=round((time.perf_counter() - started) * 1000, 1))


async def _turn(deps: Deps, ctx: TurnContext, text: str) -> AsyncIterator[TurnEvent]:
    game = ctx.game
    brief = await deps.client.case_brief(game)
    if brief.status != "playing":
        reveal = await deps.client.reveal(game)
        yield GameOver(outcome=ended(ctx, brief), reveal=reveal)
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
        ctx.pending = None  # cleared first: a replay can only come back as `repeat`
        async for event in _run_pending(deps, ctx, text, pending):
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
    async for event in _process(deps, ctx, text, brief, intent):
        yield event


async def _process(
    deps: Deps, ctx: TurnContext, text: str, brief: PlayerCaseView, intent: Intent
) -> AsyncIterator[TurnEvent]:
    config = deps.config
    game = ctx.game
    if intent.intent_confidence < config.confidence_gate:
        yield Clarify(
            reason="low_confidence",
            text="I am not sure what you want to do. Could you say it differently?",
        )
        return
    name = intent.name
    handle = intent.target
    if name in NEEDS_TARGET:
        if handle is None or intent.target_confidence < config.confidence_gate:
            yield Clarify(reason="bad_target", text="Which place or suspect do you mean?")
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
            yield Clarify(reason="mismatch", text="That does not work with what you named.")
            return
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
        line = "Give up and see the answer?"
        ctx.pending = Pending(kind="give_up", line=line)
        yield Confirm(pending="give_up", text=line)
        _remember(ctx, text, "asked to confirm giving up")
    elif name == "accuse":
        async for event in _start_accusation(deps, ctx, text):
            yield event
    else:  # meta and other
        yield Reply(speaker=None, text=HELP, source="help")
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


async def _start_accusation(deps: Deps, ctx: TurnContext, text: str) -> AsyncIterator[TurnEvent]:
    game = ctx.game
    questions = await deps.client.accusation_questions(game, text)
    decision_id = uuid.uuid4().hex
    try:
        result = await deps.decider.decide(
            questions.state,
            accusation.to_choice_questions(questions),
            node="parse_accusation",
            decision_id=decision_id,
        )
    except DeciderError as exc:
        logger.warning("the parse_accusation decision failed: %s", describe_failure(exc))
        yield Clarify(reason="error", text=APOLOGY, decision_id=decision_id)
        return
    try:
        parsed = await deps.client.interpret_accusation(game, accusation.probabilities_of(result))
    except ToolFailure as exc:
        if exc.code != "bad_argument":
            raise
        yield Clarify(reason="error", text=APOLOGY, decision_id=decision_id)
        return
    plan = await deps.client.describe_accusation(game, parsed.who, parsed.how, parsed.why)
    if plan.repeat:
        yield Clarify(
            reason="accusation",
            text="You already tried that exact accusation.",
            decision_id=decision_id,
        )
    elif plan.can_confirm and parsed.who and parsed.how and parsed.why:
        ctx.pending = Pending(
            kind="accuse", line=plan.confirmation, handles=(parsed.who, parsed.how, parsed.why)
        )
        yield Confirm(
            pending="accuse",
            text=plan.confirmation,
            warnings=plan.warnings,
            decision_id=decision_id,
        )
        _remember(ctx, text, "asked to confirm an accusation")
    elif plan.problems:
        yield Clarify(
            reason="accusation", text=accusation.missing_text(plan), decision_id=decision_id
        )
    else:
        yield Clarify(
            reason="accusation",
            text="That accusation cannot be made right now.",
            decision_id=decision_id,
        )


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
