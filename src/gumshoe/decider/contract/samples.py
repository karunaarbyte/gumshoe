"""Demo input used by the CLI and tests (matches fixtures/nimble_all_types.request.json)."""

from gumshoe.decider.contract.models import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion

DEMO_STATE = "Player says: I want to question the butler about the broken window."

DEMO_QUESTIONS: dict[str, Question] = {
    "intent": ChoiceQuestion(
        instructions="What is the player trying to do?",
        criteria={
            "action": "Physical action in the world",
            "dialogue": "Talking to a character",
            "accusation": "Accusing someone of the crime",
            "meta": "Game or UI command",
        },
    ),
    "needs_interrogation": NoulQuestion(
        instructions="Does this require questioning a character?",
    ),
    "urgency": ScoreQuestion(
        instructions="How dramatic is this moment?",
        criteria=["Mundane", "Mild", "Tense", "Dramatic", "Climactic"],
    ),
}
