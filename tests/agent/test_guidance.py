from gumshoe.agent import guidance
from gumshoe.cases.play.views import (
    LocationView,
    PlayerCaseView,
    RecordKindView,
    SuspectView,
)


def brief(*, places=(), suspects=(), attempts=3):
    """places and suspects are (name, locked) pairs."""
    return PlayerCaseView(
        intro="Lord Wulfric was murdered in the Kitchen.",
        locations=tuple(
            LocationView(number=i, handle=f"p{i}", name=n, description="d", locked=lk)
            for i, (n, lk) in enumerate(places, 1)
        ),
        suspects=tuple(
            SuspectView(number=i, handle=f"s{i}", name=n, description="d", locked=lk)
            for i, (n, lk) in enumerate(suspects, 1)
        ),
        record_kinds=(RecordKindView(key="register", label="household register"),),
        attempts_left=attempts,
        status="playing",
    )


PLACES = (("Gatehouse", False), ("Kitchen", False), ("Cellar", True))
PEOPLE = (("Maud the clerk", False), ("Hugh the steward", False), ("Gilbert the cook", True))


def test_the_short_nudge_gives_two_real_examples_from_what_is_open():
    text = guidance.short_nudge(brief(places=PLACES, suspects=PEOPLE))
    assert "search the Gatehouse" in text and "ask Maud the clerk" in text
    assert "help" in text
    assert len(text) < 200


def test_the_nudge_copes_with_nothing_open_to_name():
    assert "search" in guidance.short_nudge(brief(places=(("Cellar", True),), suspects=PEOPLE[2:]))
    assert "ask" not in guidance.short_nudge(brief(places=PLACES, suspects=PEOPLE[2:]))
    assert "search the" not in guidance.short_nudge(brief(places=PLACES[2:], suspects=PEOPLE))


def test_the_full_help_lists_every_kind_of_move_with_capped_names():
    many = tuple((f"Person {i}", False) for i in range(9))
    text = guidance.full_help(brief(places=PLACES, suspects=many))
    for word in ("Search", "Question", "records", "notebook", "Accuse", "lead"):
        assert word in text
    assert "Person 0" in text and "Person 8" not in text  # capped, not a wall of names
    assert "3 attempts" in text


def test_a_capped_list_shows_that_names_were_left_out():
    many = tuple((f"Person {i}", False) for i in range(9))
    assert "Person 2, …" in guidance.full_help(brief(places=PLACES, suspects=many))
    assert "…" not in guidance.which_text(brief(places=PLACES, suspects=PEOPLE), "interrogate")


def test_the_full_help_says_when_it_is_the_last_attempt():
    assert "last attempt" in guidance.full_help(brief(places=PLACES, suspects=PEOPLE, attempts=1))


def test_the_full_help_counts_suspects_still_to_be_found_without_naming_them():
    text = guidance.full_help(brief(places=PLACES, suspects=PEOPLE))
    assert "1 more" in text and "Gilbert" not in text
    assert "more" not in guidance.full_help(brief(places=PLACES, suspects=PEOPLE[:2]))


def test_a_locked_name_never_appears_in_any_guidance():
    b = brief(places=PLACES, suspects=PEOPLE)
    texts = [guidance.short_nudge(b)] + [
        guidance.full_help(b),
        guidance.which_text(b, "search"),
        guidance.which_text(b, "interrogate"),
        guidance.which_text(b, "records"),
        guidance.mismatch_text(b, "s3"),
        guidance.mismatch_text(b, "p3"),
        guidance.tailored(b, "search"),
        guidance.tailored(b, "records"),
    ]
    for text in texts:
        assert "Gilbert" not in text and "Cellar" not in text, text


def test_which_lists_only_what_is_open_for_the_kind_of_move():
    b = brief(places=PLACES, suspects=PEOPLE)
    assert guidance.which_text(b, "search") == "Which place? Gatehouse or Kitchen."
    assert (
        guidance.which_text(b, "interrogate")
        == "Which suspect? Maud the clerk or Hugh the steward."
    )
    assert "Gatehouse" in guidance.which_text(b, "records") and "Maud" in guidance.which_text(
        b, "records"
    )


def test_mismatch_says_what_the_named_thing_is_and_what_to_do_with_it():
    b = brief(places=PLACES, suspects=PEOPLE)
    assert "Maud the clerk is a suspect" in guidance.mismatch_text(b, "s1")
    assert "Kitchen is a place" in guidance.mismatch_text(b, "p2")
    assert guidance.mismatch_text(b, "nope") == guidance.GENERIC_MISMATCH


def test_a_tailored_line_matches_the_move_the_model_half_read():
    b = brief(places=PLACES, suspects=PEOPLE)
    assert "search the Gatehouse" in guidance.tailored(b, "search")
    assert "ask Maud the clerk" in guidance.tailored(b, "interrogate")
    assert guidance.tailored(b, "notebook") is None


def test_a_bare_help_request_is_recognised():
    for text in ("help", "Help!", "hint", "?", "help me", "  HELP  "):
        assert guidance.is_help_request(text), text
    for text in ("help me search", "who did it", "search the kitchen"):
        assert not guidance.is_help_request(text), text


async def test_no_guidance_text_from_a_real_game_gives_away_anything_hidden():
    """Built from a real long-preset game at the start, where suspects are still locked."""
    from tests.agent.fakes import Script
    from tests.agent.harness import playing
    from tests.mcp_server.helpers import castle_case

    case = castle_case(1)
    async with playing(Script(), preset="long") as h:
        b = h.brief
        locked = [s.name for s in b.suspects if s.locked] + [
            p.name for p in b.locations if p.locked
        ]
        assert locked, "the long preset starts with something locked"
        secrets = (
            locked
            + [m.label for m in case.methods]
            + [m.label for m in case.motives]
            + [f.text for f in case.facts]
        )
        texts = [guidance.full_help(b), guidance.short_nudge(b)]
        for intent in ("search", "interrogate", "talk", "records", "accuse"):
            texts += [guidance.which_text(b, intent), guidance.tailored(b, intent) or ""]
        for s in b.suspects + b.locations:  # every possible mismatch, locked or not
            texts += [
                guidance.mismatch_text(b, s.handle),
                guidance.mismatch_text(b, s.handle),
            ]
        for text in texts:
            for secret in secrets:
                assert secret.lower() not in text.lower(), (secret, text)
