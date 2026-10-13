"""One batched decision per turn: what does the player want, aimed at what, how dramatic."""

from dataclasses import dataclass

from gumshoe.cases import PlayerCaseView
from gumshoe.decider import ChoiceQuestion, DecisionResult, NoulQuestion, Question, ScoreQuestion

NO_TARGET = "none"
MAX_OPTIONS = 26  # the System One limit on options of one choice question

INTENTS: dict[str, str] = {
    "search": "The player wants to search or look around a place.",
    "interrogate": "The player wants to question a suspect, or asks a suspect something.",
    "records": "The player wants to read the records or files about a suspect or a place.",
    "talk": "The player chats with a suspect again without looking for new information.",
    "accuse": "The player names who did it, how and why, or says they want to accuse someone.",
    "notebook": "The player asks what they know so far or wants to see their notes.",
    "give_up": "The player gives up and wants to see the answer.",
    "meta": "The player asks how the game works, or issues a game command.",
    "other": "Anything else, or something that makes no sense in the game.",
}


@dataclass(frozen=True)
class Intent:
    name: str
    target: str | None  # a handle
    intent_confidence: float
    target_confidence: float
    weight: float  # score on the 0-4 scale
    confirms_pending: float | None  # P(yes) when a confirmation was pending
    decision_id: str


@dataclass(frozen=True)
class UnderstandQuestions:
    questions: dict[str, Question]
    targets: dict[str, str]  # option key (place_N, suspect_N) -> handle


def build_understand(brief: PlayerCaseView, *, pending: bool) -> UnderstandQuestions:
    criteria: dict[str, str] = {}
    targets: dict[str, str] = {}
    for place in brief.locations:
        criteria[f"place_{place.number}"] = f"The player means the place called {place.name}."
        targets[f"place_{place.number}"] = place.handle
    for suspect in brief.suspects:
        criteria[f"suspect_{suspect.number}"] = f"The player means the suspect {suspect.name}."
        targets[f"suspect_{suspect.number}"] = suspect.handle
    criteria[NO_TARGET] = "The player does not mean any one place or suspect."
    if len(criteria) > MAX_OPTIONS:
        raise ValueError(f"{len(criteria)} target options exceed the limit of {MAX_OPTIONS}")
    questions: dict[str, Question] = {
        "intent": ChoiceQuestion(
            instructions="What does the player want to do with this message?",
            criteria=dict(INTENTS),
        ),
        "target": ChoiceQuestion(
            instructions="Which place or suspect does the player's message refer to?",
            criteria=criteria,
        ),
        "weight": ScoreQuestion(
            instructions="How dramatic is this moment in the story?",
            criteria=["Mundane", "Mild", "Tense", "Dramatic", "Climactic"],
        ),
    }
    if pending:
        questions["confirms_pending"] = NoulQuestion(
            instructions=(
                "The player was just asked to confirm something. Does this message clearly "
                "say yes, go ahead?"
            )
        )
    return UnderstandQuestions(questions=questions, targets=targets)


def read_intent(result: DecisionResult, targets: dict[str, str], decision_id: str) -> Intent:
    """Raises KeyError for a missing answer and TypeError for one of the wrong type: the caller
    treats both as a failed decision."""
    intent = result.choice("intent")
    target = result.choice("target")
    confirms = (
        result.noul("confirms_pending").noul if "confirms_pending" in result.answers else None
    )
    return Intent(
        name=intent.choice if intent.choice in INTENTS else "other",
        target=targets.get(target.choice),
        intent_confidence=intent.confidence,
        target_confidence=target.confidence,
        weight=result.score("weight").score,
        confirms_pending=confirms,
        decision_id=decision_id,
    )
