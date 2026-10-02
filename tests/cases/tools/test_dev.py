from gumshoe.cases.tools.dev import simulate_lines
from tests.cases.fixtures import build_case


def test_simulate_report_lines_for_the_fixture():
    lines = simulate_lines(build_case())
    assert lines == [
        "solvable by honest deduction: yes",
        "winnable by reading everything then naming the truth: yes",
        "fewest source uses to decide the case: 2",
        "blind-guess win rate after reading everything: 4/9 (0.444)",
    ]
