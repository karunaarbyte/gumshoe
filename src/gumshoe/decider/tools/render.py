"""Plain-text formatting for CLI output."""

from collections.abc import Mapping

from gumshoe.decider.tools.compare import Outcome
from gumshoe.decider.contract.agreement import answers_agree
from gumshoe.decider.contract.models import Answer, ChoiceAnswer, DecisionResult, NoulAnswer, ScoreAnswer

COLUMN = 24


def summarise(answer: Answer) -> str:
    match answer:
        case ChoiceAnswer():
            p = answer.probabilities.get(answer.choice, float("nan"))
            return f"{answer.choice} {p:.2f}"
        case NoulAnswer():
            return f"{'yes' if answer.yes else 'no'} {answer.noul:.2f}"
        case ScoreAnswer():
            return f"{answer.score:.2f}"


def format_result(result: DecisionResult) -> str:
    lines = [f"model: {result.model}"]
    lines += [f"{name.ljust(COLUMN)}{summarise(a)}" for name, a in result.answers.items()]
    return "\n".join(lines)


def format_comparison(outcomes: Mapping[str, Outcome]) -> str:
    names = list(outcomes)
    results = {n: o.result for n, o in outcomes.items() if o.result is not None}

    questions: list[str] = []
    for result in results.values():
        for q in result.answers:
            if q not in questions:
                questions.append(q)

    lines = ["question".ljust(COLUMN) + "".join(n.ljust(COLUMN) for n in names) + "agree"]
    for q in questions:
        cells, answers = [], []
        for n in names:
            result = results.get(n)
            if result is not None and q in result.answers:
                cells.append(summarise(result.answers[q]))
                answers.append(result.answers[q])
            else:
                cells.append("-")
        agree = "" if len(answers) < 2 else ("yes" if answers_agree(answers) else "NO")
        lines.append(q.ljust(COLUMN) + "".join(c.ljust(COLUMN) for c in cells) + agree)

    latencies = [
        (f"{o.latency_ms:.0f}" if o.latency_ms is not None else "-").ljust(COLUMN)
        for o in outcomes.values()
    ]
    lines.append("latency_ms".ljust(COLUMN) + "".join(latencies))
    lines += [f"{n} error: {o.error}" for n, o in outcomes.items() if o.error]
    return "\n".join(lines)
