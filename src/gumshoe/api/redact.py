"""What a player may see of a decision (the verdicts, not the words that led to them) and of
the case brief (a locked suspect or place without its name).

The case's secret is its locked names (suspects and places the player has not reached). Any text
here may hold one: the player's own words and the state sent to the models (`state_preview`), a
model's answer (it can echo the hidden state), a question name. So this is an allow-list: each new
object is built field by field from the sets below, a field not named in them is never copied,
and a test fails when a view gains a field no set names."""

import re
from typing import Annotated

from pydantic import AfterValidator

from gumshoe.cases import LocationView, PlayerCaseView, SuspectView
from gumshoe.stats.queries import AnswerView, CallView, DecisionView

# copied as they are: numbers, flags, and strings the server makes (an id, a timestamp, the node,
# the configured backend name and its role), never model or player text
KEPT_VIEW_FIELDS = frozenset({"decision_id", "node", "ts", "fallback"})
KEPT_CALL_FIELDS = frozenset(
    {
        "backend",
        "role",
        "used",
        "cold",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "est_cost_usd",
    }
)
# copied only in part: entries whose names and verdicts are safe tokens, an error as a marker
FILTERED_VIEW_FIELDS = frozenset({"calls", "agrees"})
FILTERED_CALL_FIELDS = frozenset({"answers", "error"})
# never shown
BLANKED_VIEW_FIELDS = frozenset({"state_preview"})
BLANKED_CALL_FIELDS: frozenset[str] = frozenset()

# The nodes whose answers a player may see. Their options are tokens (`suspect_3`, never a name)
# for every place and suspect, locked ones included, plus intents, yes/no and scores. The brief
# already lists every one of those entries to the player (a locked one without its name), so a
# token answer tells them nothing new: that, not the options being visible ones only, is why
# these are safe. Every other node, parse_accusation above all, shows none.
ANSWER_NODES = frozenset({"understand", "post_check"})

# The shapes the game's own verdicts and question names take: a lowercase key such as `suspect_3`,
# `none` or `yes`, or a score such as `2.00`. A model's free text (a name, a sentence) is not one.
_SAFE_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,39}|\d{1,3}(\.\d{1,3})?")

# A failed call shows only that it failed: older rows may hold an exception's raw text.
FAILED = "failed"


def _safe(token: str) -> bool:
    return _SAFE_TOKEN.fullmatch(token) is not None


def _answers(node: str, answers: dict[str, AnswerView]) -> dict[str, AnswerView]:
    if node not in ANSWER_NODES:
        return {}
    return {
        q: AnswerView(verdict=a.verdict, confidence=a.confidence)
        for q, a in answers.items()
        if _safe(q) and _safe(a.verdict)
    }


def _call(node: str, call: CallView) -> CallView:
    return CallView(
        backend=call.backend,
        role=call.role,
        used=call.used,
        cold=call.cold,
        latency_ms=call.latency_ms,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        est_cost_usd=call.est_cost_usd,
        error=None if call.error is None else FAILED,
        answers=_answers(node, call.answers),
    )


def for_player(view: DecisionView) -> DecisionView:
    """A new view for the game's own player; `view` is not changed."""
    return DecisionView(
        decision_id=view.decision_id,
        node=view.node,
        ts=view.ts,
        fallback=view.fallback,
        state_preview="",
        calls=[_call(view.node, call) for call in view.calls],
        agrees={q: same for q, same in view.agrees.items() if _safe(q)},
    )


def _blank_locked[E: (LocationView, SuspectView)](entries: tuple[E, ...]) -> tuple[E, ...]:
    return tuple(
        e.model_copy(update={"name": "", "description": ""}) if e.locked else e for e in entries
    )


def player_brief(brief: PlayerCaseView) -> PlayerCaseView:
    """The brief as the player may see it: a locked suspect or place keeps its number, handle and
    lock, but its name and description are sent empty until it opens. The engine's own brief keeps
    them: the agent needs them to tell which entry a typed message means."""
    return brief.model_copy(
        update={
            "locations": _blank_locked(brief.locations),
            "suspects": _blank_locked(brief.suspects),
        }
    )


# The type of every brief the API sends: whatever model carries it, it is redacted on the way in.
PlayerBrief = Annotated[PlayerCaseView, AfterValidator(player_brief)]
