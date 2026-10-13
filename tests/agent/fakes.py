"""Scripted stand-ins for the decider and the language model."""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from gumshoe.agent.llm import LlmMessage
from gumshoe.decider import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionResult,
    NoulAnswer,
    Question,
    ScoreAnswer,
)

UNCLEAR = "does not clearly"  # the engine's unclear-option criteria text


class ScriptExhausted(BaseException):  # noqa: N818
    """A scripting mistake. Not an `Exception`, so take_turn's catch-all cannot turn it into
    the apology and hide it: it fails the test."""


def choice(options, pick: str, p: float = 0.9) -> ChoiceAnswer:
    keys = list(options)
    rest = (1 - p) / max(len(keys) - 1, 1)
    probabilities = {k: (p if k == pick else rest) for k in keys}
    return ChoiceAnswer(type="choice", choice=pick, probabilities=probabilities, confidence=p)


def criteria_of(question: Question) -> dict[str, str]:
    assert isinstance(question, ChoiceQuestion), f"expected a choice question, got {question.type}"
    return question.criteria


def noul(p: float) -> NoulAnswer:
    return NoulAnswer(type="noul", noul=p)


def score(x: float) -> ScoreAnswer:
    return ScoreAnswer(type="score", score=x, legend={}, probabilities={}, confidence=0.9)


def understand_answers(
    questions: Mapping[str, Question],
    *,
    intent: str,
    target: str = "none",
    intent_p: float = 0.9,
    target_p: float = 0.9,
    weight: float = 1.0,
    confirm: float | None = None,
) -> dict[str, Answer]:
    answers: dict[str, Answer] = {
        "intent": choice(criteria_of(questions["intent"]), intent, intent_p),
        "target": choice(criteria_of(questions["target"]), target, target_p),
        "weight": score(weight),
    }
    if "confirms_pending" in questions:
        answers["confirms_pending"] = noul(0.5 if confirm is None else confirm)
    return answers


def parse_answers(
    questions: Mapping[str, Question], fragments: Mapping[str, str | None], p: float = 0.9
) -> dict[str, Answer]:
    """Pick, per asked axis, the option whose criteria contain the fragment (None = unclear)."""
    answers: dict[str, Answer] = {}
    for axis, question in questions.items():
        criteria = criteria_of(question)
        fragment = fragments.get(axis)
        if fragment is None:
            pick = next(k for k, v in criteria.items() if UNCLEAR in v)
        else:
            pick = next(k for k, v in criteria.items() if fragment in v)
        answers[axis] = choice(criteria, pick, p)
    return answers


def post_check_answers(contradicts: float = 0.1, guilt: float = 0.1) -> dict[str, Answer]:
    return {"contradicts_says": noul(contradicts), "claims_guilt_or_blames_other": noul(guilt)}


class Script:
    """Per-node FIFO queues of answer builders; running dry fails the test loudly."""

    def __init__(self) -> None:
        self.queues: dict[str, list[Callable[[Mapping[str, Question]], dict[str, Answer]]]] = (
            defaultdict(list)
        )

    def understand(self, **kw) -> "Script":
        self.queues["understand"].append(lambda q: understand_answers(q, **kw))
        return self

    def parse(self, p: float = 0.9, **fragments: str | None) -> "Script":
        self.queues["parse_accusation"].append(lambda q: parse_answers(q, fragments, p))
        return self

    def post_check(self, contradicts: float = 0.1, guilt: float = 0.1) -> "Script":
        self.queues["post_check"].append(lambda q: post_check_answers(contradicts, guilt))
        return self

    def fail(self, node: str, error: Exception) -> "Script":
        def boom(_q: Mapping[str, Question]) -> dict[str, Answer]:
            raise error

        self.queues[node].append(boom)
        return self

    def __call__(
        self, node: str, state: str, questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        queue = self.queues[node]
        if not queue:
            raise ScriptExhausted(f"no scripted answer left for node {node!r}")
        return queue.pop(0)(questions)

    def left(self) -> dict[str, int]:
        return {node: len(q) for node, q in self.queues.items() if q}


class ScriptedDecider:
    name = "jev"

    def __init__(self, script: Callable[[str, str, Mapping[str, Question]], dict[str, Answer]]):
        self._script = script
        self.calls: list[tuple[str, str, str | None]] = []  # (node, state, decision_id)
        self.questions: list[Mapping[str, Question]] = []

    async def decide(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        node: str = "adhoc",
        decision_id: str | None = None,
    ) -> DecisionResult:
        self.calls.append((node, state, decision_id))
        self.questions.append(questions)
        return DecisionResult(model="fake", answers=self._script(node, state, questions))

    async def aclose(self) -> None:
        pass


class ScriptedLlm:
    def __init__(self, replies: Sequence[str | Exception]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[str, str, list[LlmMessage]]] = []

    async def complete(self, model: str, system: str, messages: Sequence[LlmMessage]) -> str:
        self.calls.append((model, system, list(messages)))
        if not self._replies:
            raise ScriptExhausted("the scripted LLM was asked for more replies than scripted")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def aclose(self) -> None:
        pass
