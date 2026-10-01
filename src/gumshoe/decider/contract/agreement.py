"""When do two backends' answers to the same question count as agreeing?

Pure logic, shared by the CLI comparison table and (in Plan 1b) the stats queries.
"""

from collections.abc import Sequence

from gumshoe.decider.contract.models import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer

# Scores are fractional positions on a rubric. Two scores agree when their whole spread is
# less than half a level. Comparing rounded levels would split 2.49/2.51 and merge 1.5/2.5.
SCORE_TOLERANCE = 0.5


def answers_agree(answers: Sequence[Answer]) -> bool:
    """True if every answer gives the same verdict. Fewer than two answers trivially agree."""
    if len(answers) < 2:
        return True
    first = answers[0]
    if not all(type(a) is type(first) for a in answers):
        return False
    if isinstance(first, ChoiceAnswer):
        return len({a.choice for a in answers if isinstance(a, ChoiceAnswer)}) == 1
    if isinstance(first, NoulAnswer):
        return len({a.yes for a in answers if isinstance(a, NoulAnswer)}) == 1
    assert isinstance(first, ScoreAnswer)
    scores = [a.score for a in answers if isinstance(a, ScoreAnswer)]
    return max(scores) - min(scores) < SCORE_TOLERANCE
