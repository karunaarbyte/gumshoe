"""What the agent says when a message is unclear, off topic or aimed at the wrong thing.

Pure text from the player-visible `PlayerCaseView`, never a model call. A locked suspect or place
is never named: the board shows it as REDACTED, and its name is revealed only as the case opens up.
"""

import re
from collections.abc import Sequence
from typing import Protocol

from gumshoe.cases import PlayerCaseView

NAME_CAP = 3  # a list of names is a hint, not the whole board
GENERIC_MISMATCH = "That does not work with what you named. Type help for ideas."
GENERIC_WHICH = "Which place or suspect do you mean?"
HELP_WORDS = frozenset({"help", "hint", "hints", "help me", "?"})


class _Card(Protocol):
    """What a suspect or a place in the brief has in common."""

    @property
    def name(self) -> str: ...

    @property
    def locked(self) -> bool: ...


def _open(items: Sequence[_Card]) -> list[str]:
    return [i.name for i in items if not i.locked]


def _names(names: list[str]) -> str:
    shown = names[:NAME_CAP]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " or " + shown[-1]


def _pick(names: list[str], round: int) -> str | None:
    return names[round % len(names)] if names else None


def _examples(brief: PlayerCaseView, round: int) -> list[str]:
    place = _pick(_open(brief.locations), round)
    who = _pick(_open(brief.suspects), round)
    out = []
    if place is not None:
        out.append(f"“search the {place}”")
    if who is not None:
        out.append(f"“ask {who} where they were”")
    return out


def short_nudge(brief: PlayerCaseView, *, round: int = 0) -> str:
    """The first answer to a message we could not read: two real examples and the way out."""
    examples = _examples(brief, round)
    if not examples:
        return "I did not catch that. Try searching a place, or type help."
    return f"I did not catch that. Try {' or '.join(examples)}, or type help."


def full_help(brief: PlayerCaseView) -> str:
    """Every kind of move, with real names (a few) and what is left to find."""
    places, people = _open(brief.locations), _open(brief.suspects)
    lines = ["Here is what you can do:"]
    if places:
        lines.append(f"• Search a place ({_names(places)}): “search the {places[0]}”.")
    if people:
        lines.append(f"• Question a suspect ({_names(people)}): “ask {people[0]} where they were”.")
    subject = people[0] if people else (places[0] if places else None)
    if subject is not None:
        lines.append(
            f"• Read the records about a suspect or place: “read the records about {subject}”."
        )
    lines.append("• Check your notebook: “what do I know?”")
    lines.append("• Accuse: “I accuse <suspect>”, once you hold a lead on them.")
    hidden = sum(1 for s in brief.suspects if s.locked)
    if hidden:
        lines.append(f"{hidden} more suspect{'s' if hidden > 1 else ''} to find: keep digging.")
    last = brief.attempts_left == 1
    lines.append(
        "This is your last attempt." if last else f"You have {brief.attempts_left} attempts left."
    )
    return "\n".join(lines)


def which_text(brief: PlayerCaseView, intent: str) -> str:
    """The question for a move that had no clear target, naming only what is open."""
    places, people = _open(brief.locations), _open(brief.suspects)
    if intent == "search" and places:
        return f"Which place? {_names(places)}."
    if intent in ("interrogate", "talk") and people:
        return f"Which suspect? {_names(people)}."
    if intent == "records" and (people or places):
        return f"Whose records? {_names(people + places)}."
    return GENERIC_WHICH


def _kind_of(brief: PlayerCaseView, handle: str) -> tuple[str, str, bool] | None:
    for s in brief.suspects:
        if s.handle == handle:
            return "suspect", s.name, s.locked
    for p in brief.locations:
        if p.handle == handle:
            return "place", p.name, p.locked
    return None


def mismatch_text(brief: PlayerCaseView, intent: str, handle: str) -> str:
    """The model read a move and a target that do not go together ("search Maud")."""
    found = _kind_of(brief, handle)
    if found is None or found[2]:
        return GENERIC_MISMATCH
    kind, name, _ = found
    if kind == "suspect":
        return f"{name} is a suspect, not a place: question them, or read the records about them."
    return f"{name} is a place, not a person: search it, or read the records about it."


def tailored(brief: PlayerCaseView, intent: str) -> str | None:
    """A hint for the move the model half-read, or None when there is nothing useful to add."""
    places, people = _open(brief.locations), _open(brief.suspects)
    if intent == "search" and places:
        return f"To search, say “search the {places[0]}”."
    if intent in ("interrogate", "talk") and people:
        return f"To question someone, say “ask {people[0]} where they were”."
    if intent == "records" and (people or places):
        return f"To read records, say “read the records about {(people + places)[0]}”."
    if intent == "accuse":
        return "To accuse, say “I accuse <suspect>”. You need a lead on them first."
    return None


def is_help_request(text: str) -> bool:
    """A message that is only a request for help, whatever its case or marks."""
    words = " ".join(re.findall(r"[a-z?]+", text.lower()))
    return words in HELP_WORDS
