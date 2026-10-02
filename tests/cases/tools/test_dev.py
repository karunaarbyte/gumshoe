from gumshoe.cases.model.entities import RecordSource
from gumshoe.cases.model.enums import RecordSubjectType
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


def test_simulate_warns_about_event_record_sources_a_player_cannot_reach():
    event_log = RecordSource(
        kind="gate_log", subject_type=RecordSubjectType.EVENT, subject="t_crime"
    )
    case = build_case()
    case = case.model_copy(update={"record_sources": (*case.record_sources, event_log)})
    lines = simulate_lines(case)
    assert lines[-1] == "note: 1 event-record source(s) cannot be reached from a player session"
    assert len(lines) == 5
