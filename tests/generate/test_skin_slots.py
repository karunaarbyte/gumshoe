import pytest

from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.generate.errors import GenerationError
from gumshoe.cases.model.entities import Location, Suspect
from gumshoe.cases.model.pack import Entry
from tests.generate.helpers import castle


def test_a_person_carries_the_name_and_the_pronoun_forms():
    assert slots.person(Entry(text="Edmund", pronoun="he")) == {
        "who": "Edmund",
        "who.subj": "he",
        "who.poss": "his",
    }
    assert (
        slots.person(Entry(text="Lord Aldric", pronoun="he"), "victim")["victim"] == "Lord Aldric"
    )
    assert slots.person(Entry(text="Sam"))["who.subj"] == "they"  # no pronoun: they


def test_a_place_carries_its_article_and_its_in_phrase():
    place = Entry(text="Chapel", article="the")
    assert slots.place(place) == {"place": "the Chapel", "place.in": "in the Chapel"}


def test_a_place_uses_its_own_preposition_and_defaults_to_in():
    deck = Entry(text="promenade deck", article="the", prep="on")
    assert slots.place(deck) == {"place": "the promenade deck", "place.in": "on the promenade deck"}
    assert slots.place(Entry(text="stage", article="the"))["place.in"] == "in the stage"


def test_a_time_comes_from_the_packs_slot_phrases_and_must_exist():
    pack = castle()
    first = slots.slot_time(pack, 0)
    assert first["time.at"] == pack.slot_defs[0].at and first["time.during"]
    with pytest.raises(GenerationError, match="time slot 99"):
        slots.slot_time(pack, 99)


def test_a_record_name_is_the_first_display_name_and_must_exist():
    pack = castle()
    kind = pack.record_defs[0]
    assert slots.record_name(pack, kind.key)["record"].endswith(kind.names[0].text)
    with pytest.raises(GenerationError, match="no display name"):
        slots.record_name(pack, "nowhere")


def test_a_suspect_is_found_in_its_roles_names_and_a_stranger_is_refused():
    pack = castle()
    role = pack.roles[0]
    name = role.names[0].text
    suspect = Suspect(
        id="s1",
        label=f"{name} the {role.noun}",
        aliases=(name,),
        role=role.key,
        motive="v1",
        secret_fact="f1",
    )
    assert slots.name_entry(pack, suspect).text == name
    stranger = suspect.model_copy(update={"role": "nobody"})
    with pytest.raises(GenerationError, match="no name entry"):
        slots.name_entry(pack, stranger)


def test_a_place_is_found_by_its_name_and_falls_back_to_the_first_entry():
    pack = castle()
    definition = pack.location_defs[0]
    unnamed = Location(id="l1", kind=definition.key)
    assert slots.place_entry(pack, unnamed) == definition.names[0]
    named = unnamed.model_copy(update={"name": definition.names[0].text})
    assert slots.place_entry(pack, named) == definition.names[0]
    with pytest.raises(GenerationError, match="no names"):
        slots.place_entry(pack, Location(id="l2", kind="nowhere"))
