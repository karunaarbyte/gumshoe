import string

import pytest

from gumshoe.cases.packs.catalogue import PACK_CATALOGUE, make
from gumshoe.cases.packs.issues import PackIssue, PackSeverity
from gumshoe.cases.packs.runner import check_pack
from gumshoe.cases.packs.suggest import did_you_mean
from gumshoe.cases.validate.catalogue import CATALOGUE
from tests.packs.fixtures import rich_pack


def test_pack_codes_never_collide_with_case_codes():
    assert set(PACK_CATALOGUE) & set(CATALOGUE) == set()


def test_every_code_names_a_stage_one_to_eight_and_a_one_line_message():
    for spec in PACK_CATALOGUE.values():
        assert 1 <= spec.stage <= 8 and spec.message and "\n" not in spec.message


@pytest.mark.parametrize("code", sorted(PACK_CATALOGUE))
def test_the_declared_params_are_exactly_the_message_fields(code):
    spec = PACK_CATALOGUE[code]
    fields = {name for _, name, _, _ in string.Formatter().parse(spec.message) if name}
    assert fields == set(spec.params)
    issue = make(code, "some.path", **{p: "x" for p in spec.params})
    assert issue.code == code and issue.stage == spec.stage and issue.path == "some.path"


def test_make_rejects_missing_or_extra_params():
    with pytest.raises(ValueError):
        make("UNKNOWN_KEY", "p")  # needs key=
    with pytest.raises(ValueError):
        make("UNKNOWN_KEY", "p", key="k", other="x")


def test_issues_sort_by_stage_code_path_then_message():
    a = PackIssue("B", PackSeverity.ERROR, 2, "p", "m")
    b = PackIssue("A", PackSeverity.ERROR, 2, "p", "m")
    c = PackIssue("Z", PackSeverity.ERROR, 1, "p", "m")
    assert sorted([a, b, c], key=PackIssue.sort_key) == [c, b, a]


def test_did_you_mean_is_deterministic_and_lists_the_known_names():
    text = did_you_mean("crypt", ["keep", "chapel", "crypts"])
    assert text == "did you mean 'crypts'? known: chapel, crypts, keep"
    assert did_you_mean("x", []) == "known: none"
    assert did_you_mean("zzzzzz", ["keep"]) == "known: keep"


def test_the_runner_on_a_valid_rich_pack_returns_a_tuple():
    got = check_pack(rich_pack())
    assert isinstance(got, tuple)
    # the tiny pack is structurally sound; only stage 5 and the stage 8 gaps fire on it
    assert {i.stage for i in got} == {5, 8}
