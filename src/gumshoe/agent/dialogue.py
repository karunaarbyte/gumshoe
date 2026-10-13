"""Voicing a suspect: persona prompt, draft, leak gate (`check_reply`), redraft, canned line.

`check_reply` is the hard gate: only a draft it accepts, or the canned line, is ever returned.
A rejected draft's text is never kept, logged or sent anywhere except back to nobody: the retry
prompt names only the violation categories.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from gumshoe.agent.deps import Deps
from gumshoe.agent.events import PostCheck
from gumshoe.agent.llm import LlmError, LlmMessage
from gumshoe.cases import NotebookView, PersonaBrief
from gumshoe.decider import DeciderError, NoulQuestion, Question


@dataclass(frozen=True)
class Draft:
    text: str
    source: Literal["draft", "canned"]
    degraded: bool
    check_ok: bool
    violations: tuple[str, ...]


def canned_line(persona: PersonaBrief) -> str:
    word = persona.smalltalk_allow[0] if persona.smalltalk_allow else "Nothing"
    return f'{persona.name} looks away and says only: "{word}."'


def persona_system(persona: PersonaBrief, evidence: Sequence[str]) -> str:
    said = "\n".join(f"- {s}" for s in persona.says) or "none yet"
    lines = [
        f"You are {persona.name}, a suspect questioned by a detective in a mystery game.",
        "Answer in the first person, in one to three short sentences.",
        f"Speak in this style: {persona.style}.",
        f"Your traits: {', '.join(persona.traits)}.",
        "These are the only statements you have given the detective so far:",
        said,
        "Never name a person, a method or a motive that is not in those statements or in the "
        "detective's own question. If you have nothing to add, deflect with small talk using "
        f"only words like: {', '.join(persona.smalltalk_allow)}.",
    ]
    if evidence:
        lines.append("The detective holds evidence against what you said:")
        lines.extend(f"- {e}" for e in evidence)
    return "\n".join(lines)


def evidence_against(name: str, notebook: NotebookView) -> list[str]:
    """Contradictions whose lie fact was said by this suspect (matched by display name, since
    a contradiction carries only fact handles)."""
    speaker_of = {f.handle: f.speaker for s in notebook.sections for f in s.facts}
    return [c.text for c in notebook.contradictions if speaker_of.get(c.lie) == name]


def _messages(history: Sequence[tuple[str, str]], player_text: str) -> list[LlmMessage]:
    messages: list[LlmMessage] = []
    for said, answer in history:
        messages.append(LlmMessage(role="user", content=said))
        messages.append(LlmMessage(role="assistant", content=answer))
    messages.append(LlmMessage(role="user", content=player_text))
    return messages


async def draft_reply(
    deps: Deps,
    *,
    game: str,
    suspect: str,
    persona: PersonaBrief,
    player_text: str,
    history: Sequence[tuple[str, str]],
    model: str,
    evidence: Sequence[str],
) -> Draft:
    base = persona_system(persona, evidence)
    messages = _messages(history, player_text)
    canned = Draft(canned_line(persona), "canned", False, True, ())
    system = base
    for _ in range(deps.config.max_redrafts + 1):
        try:
            raw = await deps.llm.complete(model, system, messages)
        except LlmError:
            return Draft(canned.text, "canned", True, True, ())
        text = raw.strip()[: deps.config.max_text]
        if not text:
            system = base + "\nYour last answer was empty. Answer the detective in a sentence."
            continue
        check = await deps.client.check_reply(game, suspect, player_text, text)
        if check.ok:
            return Draft(text, "draft", False, True, ())
        categories = ", ".join(sorted({v.category for v in check.violations}))
        system = (
            base
            + f"\nYour last draft was rejected because it named a {categories} the detective has "
            "not met. Rewrite it without naming anything outside your statements."
        )
    return canned


def post_check_questions() -> dict[str, Question]:
    return {
        "contradicts_says": NoulQuestion(
            instructions=(
                "Does the suspect's reply contradict any of the statements the suspect gave "
                "earlier?"
            )
        ),
        "claims_guilt_or_blames_other": NoulQuestion(
            instructions="Does the reply confess to the crime, or accuse another suspect of it?"
        ),
    }


async def post_check(
    deps: Deps, *, reply: str, persona: PersonaBrief, evidence: Sequence[str]
) -> PostCheck:
    """Advisory: recorded and shown, never used to change or block a reply."""
    decision_id = uuid.uuid4().hex
    state = "\n".join(
        [
            f"The suspect {persona.name} replied: {reply}",
            "Statements the suspect gave earlier:",
            *(f"- {s}" for s in persona.says),
            *(
                ["Evidence the detective holds against them:", *(f"- {e}" for e in evidence)]
                if evidence
                else []
            ),
        ]
    )
    try:
        result = await deps.decider.decide(
            state, post_check_questions(), node="post_check", decision_id=decision_id
        )
        return PostCheck(
            decision_id=decision_id,
            contradicts_says=result.noul("contradicts_says").noul,
            claims_guilt_or_blames_other=result.noul("claims_guilt_or_blames_other").noul,
            failed=False,
        )
    except (DeciderError, KeyError, TypeError):
        return PostCheck(
            decision_id=decision_id,
            contradicts_says=None,
            claims_guilt_or_blames_other=None,
            failed=True,
        )
