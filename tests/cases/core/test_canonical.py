from enum import StrEnum

import pytest

from gumshoe.cases.core.canonical import canonical_json


def test_key_order_does_not_matter():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1}) == b'{"a":2,"b":1}'


def test_tuples_and_lists_serialise_the_same():
    assert canonical_json((1, 2, 3)) == canonical_json([1, 2, 3]) == b"[1,2,3]"


def test_list_order_is_significant():
    assert canonical_json([1, 2]) != canonical_json([2, 1])


def test_nested_structures():
    value = {"z": [{"b": None, "a": True}], "a": {"y": 1, "x": "t"}}
    assert canonical_json(value) == b'{"a":{"x":"t","y":1},"z":[{"a":true,"b":null}]}'


def test_floats_are_rejected():
    with pytest.raises(TypeError, match="floats"):
        canonical_json({"x": 1.5})


def test_non_string_keys_are_rejected():
    with pytest.raises(TypeError, match="keys"):
        canonical_json({1: "a"})


def test_unsupported_types_are_rejected():
    with pytest.raises(TypeError, match="unsupported"):
        canonical_json({"x": {1, 2}})


def test_booleans_are_not_confused_with_integers():
    assert canonical_json([True, 1, False, 0]) == b"[true,1,false,0]"


def test_unicode_is_normalised_to_nfc_and_not_escaped():
    composed, decomposed = "é", "é"
    assert canonical_json(composed) == canonical_json(decomposed) == '"é"'.encode()
    assert canonical_json({decomposed: 1}) == canonical_json({composed: 1})


def test_enums_serialise_as_their_value():
    class Colour(StrEnum):
        RED = "red"

    assert canonical_json({"c": Colour.RED}) == b'{"c":"red"}'


def test_keys_that_collide_after_normalisation_are_rejected():
    with pytest.raises(TypeError, match="collide"):
        canonical_json({"é": 1, "é": 2})
