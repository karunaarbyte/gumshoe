"""Developer-only simulator report. Never reachable from a player surface."""

from gumshoe.cases.model.case import Case
from gumshoe.cases.simulate.blind import blind_guess_win_probability
from gumshoe.cases.simulate.oracle import SearchLimitExceeded, judge, min_sources


def simulate_lines(case: Case) -> list[str]:
    verdict = judge(case)
    try:
        fewest = min_sources(case)
        fewest_text = "no play decides it" if fewest is None else str(fewest)
    except SearchLimitExceeded:
        fewest_text = "search limit reached"
    blind = blind_guess_win_probability(case)
    return [
        f"solvable by honest deduction: {'yes' if verdict.single_survivor else 'no'}",
        "winnable by reading everything then naming the truth: "
        f"{'yes' if verdict.can_win else 'no'}",
        f"fewest source uses to decide the case: {fewest_text}",
        f"blind-guess win rate after reading everything: {blind} ({float(blind):.3f})",
    ]
