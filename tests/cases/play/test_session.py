import pytest

from gumshoe.cases.model.serialize import dump_case
from gumshoe.cases.play.session import (
    FALLBACK_CONTRADICTION,
    GameOver,
    GameSession,
    StateMismatch,
    load_session,
)
from gumshoe.cases.play.state import PlayState
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact


def session(case=None, salt="salt-1"):
    return GameSession(case or build_case(), salt)


def handle_of(items, name):
    return next(i.handle for i in items if i.name == name)


def test_the_brief_lists_everyone_sorted_by_name_with_locked_flags():
    brief = session().brief()
    assert [(x.number, x.name, x.locked) for x in brief.locations] == [
        (1, "The cellar", True),
        (2, "The garden", False),
        (3, "The study", False),
    ]
    assert [(x.number, x.name) for x in brief.suspects] == [(1, "Anna"), (2, "Boris"), (3, "Clara")]
    assert [(k.key, k.label) for k in brief.record_kinds] == [
        ("gate_log", "gate log"),
        ("ledger", "ledger"),
    ]
    assert brief.attempts_left == 3 and brief.status == "playing"
    assert brief.intro.startswith("A winter evening")


def test_handles_are_opaque_deterministic_per_salt_and_differ_across_salts():
    a, b, c = session(salt="x").brief(), session(salt="x").brief(), session(salt="y").brief()
    assert a == b and a.locations[0].handle != c.locations[0].handle
    assert a.locations[0].handle.startswith("h_") and "l_cellar" not in a.locations[0].handle


def test_search_returns_new_facts_in_id_order_and_reports_what_opened():
    s = session()
    garden = handle_of(s.brief().locations, "The garden")
    result = s.search(garden)
    assert (result.kind, result.label, result.status) == ("search", "The garden", "ok")
    assert [f.text for f in result.new_facts] == [
        "The gardener swears Anna was among the roses when the bell rang.",
        "A brass key lies under the garden bench.",
    ]
    assert result.opened == ("The cellar",)
    assert s.brief().locations[0].locked is False  # the cellar is now open


def test_a_locked_place_says_locked_and_a_repeat_says_nothing_new():
    s = session()
    cellar = handle_of(s.brief().locations, "The cellar")
    assert s.search(cellar).status == "locked"
    study = handle_of(s.brief().locations, "The study")
    s.search(study)
    assert s.search(study).status == "nothing_new"


def test_unknown_handles_and_kinds_are_unknown_not_errors():
    s = session()
    assert s.search("h_bogus").status == "unknown"
    assert s.interrogate("h_bogus").status == "unknown"
    boris = handle_of(s.brief().suspects, "Boris")
    assert s.check_records("h_bogus").status == "unknown"
    assert s.check_records(boris, "nonsense").status == "unknown"
    garden = handle_of(s.brief().locations, "The garden")
    assert s.search(boris).status == "unknown"  # a suspect handle is not a location
    assert s.interrogate(garden).status == "unknown"


def test_check_records_without_a_kind_aggregates_and_says_which_kinds_contributed():
    s = session()
    study = handle_of(s.brief().locations, "The study")
    result = s.check_records(study)
    assert result.status == "ok" and result.kinds == ("gate log",)
    assert [f.text for f in result.new_facts] == [
        "The victim's estate passes to the crown.",
        "The victim had no entanglements at all.",
        "A moneylender's note was pinned to the door.",
    ]
    boris = handle_of(s.brief().suspects, "Boris")
    assert s.check_records(boris).kinds == ("ledger",)


def test_a_known_kind_about_a_subject_with_no_such_pair_is_empty_not_unknown():
    s = session()
    garden = handle_of(s.brief().locations, "The garden")
    assert s.check_records(garden, "ledger").status == "nothing_new"


def test_a_contradiction_surfaces_with_its_text_and_marks_the_lie():
    s = session()
    anna = handle_of(s.brief().suspects, "Anna")
    s.check_records(anna, "ledger")
    result = s.interrogate(anna)
    assert len(result.contradictions) == 1
    assert result.contradictions[0].text == (
        "Anna says the cellar, but the ledger places her in the garden."
    )
    lie = next(f for f in result.new_facts if f.text == "I was down in the cellar all evening.")
    assert lie.contradicted is True and lie.speaker == "Anna"
    other = next(f for f in result.new_facts if f.text.startswith("I saw Boris"))
    assert other.contradicted is False


def test_the_static_fallback_text_is_used_when_a_lie_has_no_contradiction_text():
    case = replace_fact(build_case(), "f_lie_anna", contradiction=None)
    s = session(case)
    anna = handle_of(s.brief().suspects, "Anna")
    s.interrogate(anna)
    result = s.check_records(anna, "ledger")
    assert result.contradictions[0].text == FALLBACK_CONTRADICTION.format(
        text="I was down in the cellar all evening."
    )


def test_the_notebook_groups_by_source_and_relates_to_names_without_effect_kinds():
    s = session()
    garden = handle_of(s.brief().locations, "The garden")
    anna = handle_of(s.brief().suspects, "Anna")
    s.search(garden)
    s.interrogate(anna)
    book = s.notebook()
    assert [sec.source for sec in book.sections] == ["Anna", "The garden"]
    garden_facts = {f.text: f for f in book.sections[1].facts}
    assert garden_facts[
        "The gardener swears Anna was among the roses when the bell rang."
    ].relates_to == ("Anna",)
    assert garden_facts["A brass key lies under the garden bench."].relates_to == ()
    assert book.contradictions == ()


def test_actions_after_the_game_ends_raise_game_over_instead_of_changing_state():
    s = session()
    s.give_up()
    study = handle_of(s.brief().locations, "The study")
    with pytest.raises(GameOver):
        s.search(study)
    assert s.status == "lost"


def test_a_state_from_another_case_is_refused():
    with pytest.raises(StateMismatch):
        GameSession(build_case(), "s", state=PlayState(case_digest="not-this-case"))


def test_a_save_round_trips_through_state_json():
    s = session()
    s.search(handle_of(s.brief().locations, "The study"))
    again = load_session(dump_case(build_case()), "salt-1", s.state_json())
    assert again.notebook() == s.notebook() and again.brief() == s.brief()


def test_no_view_leaks_an_id_a_truth_label_or_an_effect_kind_over_a_full_read_through():
    case = build_case()
    s = session(case)
    blobs: list[str] = []
    brief = s.brief()
    blobs.append(brief.model_dump_json())
    for loc in brief.locations:
        blobs.append(s.search(loc.handle).model_dump_json())
    for sus in brief.suspects:
        blobs.append(s.interrogate(sus.handle).model_dump_json())
    for subject in (*brief.locations, *brief.suspects):
        blobs.append(s.check_records(subject.handle).model_dump_json())
    blobs.append(s.notebook().model_dump_json())
    blobs.append(s.brief().model_dump_json())
    text = "\n".join(blobs)
    ids = (
        [x.id for x in case.suspects]
        + [x.id for x in case.locations]
        + [x.id for x in case.methods]
        + [x.id for x in case.motives]
        + [x.id for x in case.facts]
        + [x.id for x in case.timeline]
    )
    assert [i for i in ids if i in text] == []
    for label in ("poisoned in the wine", "to cover a gambling debt"):
        assert label not in text
    for word in ("rules_out", "supports", "proves", "truthful"):
        assert word not in text


def test_a_ghost_id_in_start_facts_is_ignored():
    case = build_case()
    ghost = case.model_copy(
        update={"start": case.start.model_copy(update={"facts": (*case.start.facts, "f_ghost")})}
    )
    s = session(ghost)
    assert "f_ghost" not in s.state_json()
    assert s.notebook() == session().notebook()


def test_give_up_after_the_game_ended_raises_game_over():
    s = session()
    s.give_up()
    with pytest.raises(GameOver):
        s.give_up()
    assert s.status == "lost"
