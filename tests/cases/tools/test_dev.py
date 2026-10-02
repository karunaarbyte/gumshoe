from gumshoe.cases.tools.dev import simulate_lines
from tests.cases.fixtures import build_case
from tests.cases.helpers import drop_fact


def test_simulate_report_lines_for_the_fixture():
    lines = simulate_lines(build_case())
    assert lines == [
        "solvable by honest deduction: yes",
        "winnable by reading everything then naming the truth: yes",
        "fewest source uses to decide the case: 2",
        "blind-guess win rate after reading everything: 4/9 (0.444)",
    ]


def test_solvable_line_counts_a_proof_not_just_rule_outs():
    """HOW is settled by the poison trace's `proves`, though the rule-outs are gone and several
    methods still survive: the report must agree with `fewest source uses`."""
    case = drop_fact(drop_fact(build_case(), "f_absent_dagger"), "f_absent_rope")
    lines = simulate_lines(case)
    assert lines[0] == "solvable by honest deduction: yes"
