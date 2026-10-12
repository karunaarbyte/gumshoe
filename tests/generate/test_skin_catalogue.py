import pytest

from gumshoe.cases.generate.skin_catalogue import SKIN_CATALOGUE, make
from gumshoe.cases.packs.catalogue import PACK_CATALOGUE
from gumshoe.cases.validate.catalogue import CATALOGUE


def test_skin_codes_collide_with_no_case_or_pack_code():
    assert set(SKIN_CATALOGUE) & set(CATALOGUE) == set()
    assert set(SKIN_CATALOGUE) & set(PACK_CATALOGUE) == set()


def test_an_issue_fills_in_its_message():
    issue = make("BAD_RENDER", "intro", problem="a stray brace")
    assert (issue.code, issue.path) == ("BAD_RENDER", "intro")
    assert issue.message == "the rendered text has a stray brace"


def test_an_issue_refuses_an_unknown_code_and_the_wrong_parameters():
    with pytest.raises(KeyError):
        make("NO_SUCH_CODE", "intro")
    with pytest.raises(ValueError, match="takes"):
        make("BLANK_TEXT", "intro", extra=1)
    with pytest.raises(ValueError, match="takes"):
        make("BAD_RENDER", "intro")
