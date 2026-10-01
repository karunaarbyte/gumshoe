import pytest

from gumshoe.cases.core.text import STOPWORDS, normalise, stem, tokens


def test_normalise_lowercases_strips_punctuation_and_collapses_space():
    assert normalise("  Struck with a CANDLESTICK!! ") == "struck with a candlestick"
    assert normalise("Mr. O'Neil, the cook") == "mr o neil the cook"


def test_normalise_applies_nfc():
    assert normalise("Café") == normalise("Café") == "café"


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("stabbed", "stab"),
        ("stab", "stab"),
        ("poisoned", "poison"),
        ("poison", "poison"),
        ("poisons", "poison"),
        ("strangled", "strangl"),
        ("strangle", "strangl"),
        ("strangling", "strangl"),
        ("gambling", "gambl"),
        ("owed", "owed"),  # too short to strip
        ("debt", "debt"),
        ("stewards", "steward"),
        ("inheritance", "inheritanc"),
        ("inherit", "inherit"),
    ],
)
def test_stem(word, expected):
    assert stem(word) == expected


def test_tokens_drop_stopwords_and_stem():
    assert tokens("Struck with a candlestick") == ("struck", "candlestick")
    assert tokens("the poisoned wine") == ("poison", "wine")


def test_stopwords_are_lowercase_and_nonempty():
    assert STOPWORDS and all(w == w.lower() for w in STOPWORDS)


def test_empty_text_has_no_tokens():
    assert tokens("") == ()
    assert tokens("the of a") == ()


@pytest.mark.parametrize(
    ("singular", "plural"), [("note", "notes"), ("cake", "cakes"), ("mine", "mines")]
)
def test_plural_and_singular_of_e_words_share_a_stem(singular, plural):
    assert stem(singular) == stem(plural)
