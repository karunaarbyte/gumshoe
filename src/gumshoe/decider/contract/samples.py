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

# Twelve player inputs spanning clear, ambiguous, compound and nonsense phrasing.
DEMO_PLAYER_INPUTS: tuple[str, ...] = (
    "I search the study for fingerprints",
    "I accuse the butler!",
    "what do I know so far?",
    "show me the map",
    "ask the maid where she was at 9pm",
    "i guess i'll look around, maybe talk to someone",
    "asdf",
    "I sneak in and pick the lock then question the cook",
    "examine the broken window",
    "who had a motive?",
    "I think it was the gardener, but I'm not sure",
    "save my game",
)
