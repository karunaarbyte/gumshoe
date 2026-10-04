"""A minimal hand-written case used by model-level tests (the full fixture is built in Task 10)."""

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Event,
    Fact,
    Limits,
    Location,
    Method,
    Motive,
    RecordSource,
    SourceRef,
    Spec,
    Start,
    Suspect,
    Truth,
)
from gumshoe.cases.model.enums import FactKind, RecordSubjectType, SourceKind


def tiny_limits() -> Limits:
    return Limits(
        solution_min=1,
        solution_max=9,
        depth_min=0,
        depth_max=3,
        actions_min=1,
        actions_max=9,
        decisive_pct_max=50,
    )


def tiny_case() -> Case:
    spec = Spec(
        preset="custom",
        suspects=2,
        methods=1,
        motives=2,
        locations=1,
        record_kinds=1,
        slots=4,
        opportunity=1,
        limits=tiny_limits(),
    )
    return Case(
        id="c_tiny",
        spec=spec,
        scene_type="study_murder",
        truth=Truth(who="s_a", how="m_x", why="v_a"),
        start=Start(locations=("l_x",), suspects=("s_b", "s_a"), facts=()),
        suspects=(
            Suspect(
                id="s_b",
                label="Bea the cook",
                role="cook",
                motive="v_b",
                secret_fact="f_two",
                display_name="Bea",
                description="A cook.",
            ),
            Suspect(
                id="s_a",
                label="Abe the maid",
                role="maid",
                motive="v_a",
                secret_fact="f_two",
                display_name="Abe",
                description="A maid.",
            ),
        ),
        locations=(Location(id="l_x", kind="study", name="The study", description="Dusty."),),
        record_sources=(
            RecordSource(kind="ledger", subject_type=RecordSubjectType.SUSPECT, subject="s_a"),
        ),
        methods=(Method(id="m_x", label="struck with a candlestick", type="blunt"),),
        motives=(
            Motive(id="v_b", label="out of jealousy", type="jealousy"),
            Motive(id="v_a", label="to cover a debt", type="debt"),
        ),
        timeline=(Event(id="t_1", slot=2, actor="s_a", place="l_x", action="crime"),),
        facts=(
            Fact(
                id="f_two",
                kind=FactKind.SECRET,
                source=SourceRef(kind=SourceKind.RECORD, target="ledger", subject="s_a"),
                text="A ledger entry.",
            ),
            Fact(
                id="f_one",
                kind=FactKind.CLUE,
                source=SourceRef(kind=SourceKind.SEARCH, target="l_x"),
                text="A candlestick.",
            ),
        ),
        intro="A quiet house.",
    )
