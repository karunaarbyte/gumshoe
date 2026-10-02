from gumshoe.cases.packs.check.lint import (
    SAMPLES,
    article_mismatch,
    double_space,
    doubled_word,
    mid_sentence_capital,
    placeholders,
    render,
    stray_brace,
)


def test_placeholders_lists_names_without_the_caret():
    assert placeholders("{^who} met {who.poss} friend {place.in}") == [
        "who",
        "who.poss",
        "place.in",
    ]


def test_render_substitutes_and_capitalises_on_a_caret():
    assert render("{^who} was {place.in}.", SAMPLES[0]) == "Edmund was in the Chapel."
    assert render("{who} {time.at}", SAMPLES[1]) == "Maud at the feast"


def test_stray_and_nested_braces_are_detected():
    assert stray_brace("{who")
    assert stray_brace("{{who}}")
    assert stray_brace("who}")
    assert not stray_brace("{who} and {^place}")


def test_doubled_word_double_space_and_article():
    assert doubled_word("the the door") == "the"
    assert doubled_word("the door") is None
    assert double_space("a  b") and not double_space("a b")
    assert article_mismatch("a ash heap") == "a ash"
    assert article_mismatch("an door") == "an door"
    assert article_mismatch("a door and an axe") is None


def test_mid_sentence_capital_ignores_the_first_word_I_and_sentence_starts():
    assert mid_sentence_capital("The gate log shows {who}.") is None
    assert mid_sentence_capital("It was late. Then I left.") is None
    assert mid_sentence_capital("smells of Ink") == "Ink"
    # an abbreviation is flagged too: names belong in placeholders, not in the template text
    assert mid_sentence_capital("{^who} was seen at St. Anne") == "St"


def test_lints_are_total_on_odd_input():
    for odd in ["", "...", "{}", "{^}", "日本語 é", "a", "an", "  "]:
        placeholders(odd)
        render(odd, SAMPLES[0])
        stray_brace(odd)
        doubled_word(odd)
        double_space(odd)
        article_mismatch(odd)
        mid_sentence_capital(odd)
