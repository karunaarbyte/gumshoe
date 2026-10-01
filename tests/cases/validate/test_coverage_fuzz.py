import random
import time

import pytest

from gumshoe.cases.model.entities import Fact, SourceRef
from gumshoe.cases.model.enums import FactKind, SourceKind
from gumshoe.cases.validate import runner
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Profile
from tests.cases.fixtures import TINY_PRESETS, build_case, build_pack, build_strict_case
from tests.cases.fuzz import corrupt
from tests.cases.mutations import MUTATIONS, run_mutation


def test_every_catalogue_code_has_exactly_one_mutation_and_vice_versa():
    assert set(MUTATIONS) == set(CATALOGUE)


def test_all_eleven_groups_are_registered():
    assert sorted(runner.RUNNERS) == list(range(1, 12))


def test_mutations_run_under_the_full_validator_with_their_declared_cascades():
    for code, m in MUTATIONS.items():
        report = run_mutation(m)
        assert code in report.codes(), code
        assert report.codes() == m.expected, (code, sorted(report.codes()), sorted(m.expected))


def test_imported_profile_demotes_statistical_rules_to_warnings_but_keeps_hard_rules():
    for code in (
        "FACTS_UNEVEN",
        "SHAPE_MISMATCH",
        "TRUTH_DEPTH_EXTREME",
        "CULPRIT_UNIQUE_EXTREME",
        "LABEL_LENGTH_SKEW",
        "SINGLE_POINT_OF_FAILURE",
    ):
        case = MUTATIONS[code].apply(build_case())
        report = runner.validate(case, profile=Profile.IMPORTED)
        assert report.ok, code
        assert all(i.severity.value == "warning" for i in report.issues if i.code == code)
    hard = runner.validate(
        MUTATIONS["TRUTH_RULED_OUT"].apply(build_case()), profile=Profile.IMPORTED
    )
    assert not hard.ok


def test_reports_are_sorted_by_group_then_code():
    report = runner.validate(MUTATIONS["FACTS_UNEVEN"].apply(build_case()), profile=Profile.CUSTOM)
    keys = [i.sort_key() for i in report.issues]
    assert keys == sorted(keys)


def test_a_huge_case_is_rejected_quickly():
    many = tuple(
        Fact(
            id=f"f_{i}",
            kind=FactKind.CLUE,
            source=SourceRef(kind=SourceKind.SEARCH, target="l_study"),
        )
        for i in range(10_000)
    )
    start = time.perf_counter()
    report = runner.validate(
        build_case().model_copy(update={"facts": many}), profile=Profile.STRICT
    )
    assert report.codes() == {"TOO_LARGE"} and time.perf_counter() - start < 1.0


@pytest.mark.parametrize("seed", range(8))
def test_validate_never_crashes_on_type_valid_corruptions(seed):
    rng = random.Random(seed)
    for step in range(60):
        case = corrupt(build_case() if rng.random() < 0.5 else build_strict_case(), rng)
        for profile in Profile:
            report = runner.validate(case, build_pack(), profile, TINY_PRESETS)
            assert isinstance(report.canonical(), bytes)
            # a crash inside a rule would surface here as INTERNAL_ERROR: that is a validator bug
            assert "INTERNAL_ERROR" not in report.codes(), f"seed={seed} step={step} {profile}"


@pytest.mark.parametrize("seed", range(4))
def test_validate_returns_a_report_even_for_wrong_types(seed):
    rng = random.Random(1000 + seed)
    for step in range(40):
        case = corrupt(build_case(), rng, smuggle=True)
        report = runner.validate(case, build_pack(), Profile.STRICT, TINY_PRESETS)
        assert isinstance(report.canonical(), bytes), f"seed={seed} step={step}"
        assert not report.ok, f"a wrongly typed case validated clean: seed={seed} step={step}"
