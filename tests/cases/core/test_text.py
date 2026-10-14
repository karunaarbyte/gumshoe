import pytest

from gumshoe.cases.core.text import STOPWORDS, gate_tokens, normalise, stem, tokens


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


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("\uff50\uff4f\uff49\uff53\uff4f\uff4e", "poison"),  # full-width letters
        ("poi\u200bson", "poison"),  # a zero-width space inside the word
        ("poi\u00adson", "poison"),  # a soft hyphen
        ("p\u043eison", "poison"),  # a Cyrillic o
        ("POISON", "poison"),
        ("p-o-i-s-o-n", "poison"),  # spelled out with hyphens
        ("P O I S O N", "poison"),  # spelled out with spaces
        ("p.o.i.s.o.n", "poison"),
        ("cross-bow", "crossbow"),
        ("Poisoner", "poison"),
        ("poisoners", "poison"),
        ("poisonous", "poison"),
        ("strangler", "strangl"),
        ("blackmailer", "blackmail"),
        ("fearful", "fear"),
        ("knives", "knif"),
        ("knife", "knif"),
        ("daggers", "dagger"),
    ],
)
def test_gate_tokens_see_through_disguises_and_endings(text, word):
    assert word in gate_tokens(text)


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("I was in the stable.", "stab"),  # no prefix matching
        ("hunger for power", "hung"),  # -er is stripped only from long words
        ("under cover of night", "cov"),
        ("I saw a man", "isawaman"),  # one-letter words are joined only in a run of letters
    ],
)
def test_gate_tokens_do_not_over_reach(text, word):
    assert word not in gate_tokens(text)


def test_gate_tokens_drop_stopwords_and_are_deterministic():
    assert gate_tokens("the poisoned wine") == frozenset({"poison", "wine"})
    assert gate_tokens("") == frozenset()


def test_the_case_engine_tokens_are_unchanged_by_the_gate():
    """Generation and validation keep `tokens`: the gate's stricter rules must not leak into them,
    or generated cases (and every save) would change."""
    assert tokens("Poisoner") == ("poisoner",)
    assert tokens("\uff50\uff4f\uff49\uff53\uff4f\uff4e") == (
        "\uff50\uff4f\uff49\uff53\uff4f\uff4e",
    )
