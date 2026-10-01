import pytest

from gumshoe.cases.validate import runner
from gumshoe.cases.validate.catalogue import CATALOGUE
from gumshoe.cases.validate.report import Profile
from tests.cases.fixtures import build_case
from tests.cases.mutations import MUTATIONS, implemented_codes, run_mutation


def test_the_fixture_is_clean_under_the_implemented_groups():
    report = runner.validate(build_case(), profile=Profile.CUSTOM)
    assert report.issues == () and report.skipped_groups == ()


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_mutation_reports_exactly_its_declared_cascade(code):
    mutation = MUTATIONS[code]
    report = run_mutation(mutation)
    scope = implemented_codes()
    if CATALOGUE[code].group in set(runner.RUNNERS):
        assert code in report.codes(), f"{code} not reported; got {sorted(report.codes())}"
    assert report.codes() == mutation.expected & scope, (
        f"{code}: got {sorted(report.codes())}, expected {sorted(mutation.expected & scope)}"
    )


def test_every_mutation_targets_a_catalogue_code():
    assert set(MUTATIONS) <= set(CATALOGUE)
