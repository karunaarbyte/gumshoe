import hashlib

import pytest

from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.core.ids import ID_PATTERN, is_valid_id, make_id


def test_domain_digest_is_sha256_of_domain_nul_payload():
    expected = hashlib.sha256(b"dom\0payload").hexdigest()
    assert domain_digest("dom", b"payload") == expected


def test_domains_separate_digests():
    assert domain_digest("a", b"x") != domain_digest("b", b"x")


@pytest.mark.parametrize("good", ["s_ab", "f_0123abcd", "l_study", "ab", "a" + "b" * 31])
def test_valid_ids(good):
    assert is_valid_id(good)
    assert ID_PATTERN.fullmatch(good)


@pytest.mark.parametrize("bad", ["", "a", "S_x", "1ab", "a-b", "a b", "a" * 33, "é_x", "a\n"])
def test_invalid_ids(bad):
    assert not is_valid_id(bad)


def test_make_id_is_deterministic_and_valid():
    first = make_id("f", 7, "castle", "alibi", 3)
    assert first == make_id("f", 7, "castle", "alibi", 3)
    assert is_valid_id(first)
    assert first.startswith("f_") and len(first) == 10


def test_make_id_changes_with_any_part():
    assert make_id("f", 1, "a") != make_id("f", 2, "a")
    assert make_id("f", 1, "a") != make_id("f", 1, "b")
    assert make_id("f", 1, "a") != make_id("s", 1, "a")
    assert make_id("f", "ab", "c") != make_id("f", "a", "bc")  # parts are separated


def test_make_id_rejects_a_bad_prefix():
    with pytest.raises(ValueError):
        make_id("F", 1)
    with pytest.raises(ValueError):
        make_id("toolong", 1)


def test_make_id_distinguishes_types_and_embedded_separators():
    assert make_id("f", 1) != make_id("f", "1")
    assert make_id("f", "a\0b", "c") != make_id("f", "a", "b\0c")
