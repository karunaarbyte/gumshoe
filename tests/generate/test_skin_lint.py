import pytest

from gumshoe.cases.core.text import tokens
from gumshoe.cases.generate import skin_slots as slots
from gumshoe.cases.generate.skin_lint import lint
from gumshoe.cases.model.enums import FactKind
from gumshoe.cases.packs.check.hygiene import candidate_tokens
from gumshoe.cases.packs.check.lint import phrase
from tests.generate.helpers import PACKS, PRESET_NAMES, pack_of
from tests.generate.skin_helpers import made

CASES = [(seed, preset) for preset in PRESET_NAMES for seed in range(12)]


@pytest.fixture(params=PACKS)
def pack_id(request) -> str:
    return request.param


def codes(case, pack_id) -> set[str]:
    return {i.code for i in lint(case, pack_of(pack_id))}


def edit_fact(case, fact_id, **changes):
    facts = tuple(f.model_copy(update=changes) if f.id == fact_id else f for f in case.facts)
    return case.model_copy(update={"facts": facts})


def first(case, kind, **match):
    return next(
        f
        for f in case.facts
        if f.kind is kind and all(getattr(f, k) == v for k, v in match.items())
    )


@pytest.mark.parametrize(("seed", "preset"), CASES)
def test_a_generated_case_is_clean(pack_id, seed, preset):
    assert lint(made(seed, preset, pack_id), pack_of(pack_id)) == ()


def test_a_blank_text_is_reported_and_nothing_else(pack_id):
    case = made(1, "standard", pack_id)
    fact = case.facts[0]
    assert codes(edit_fact(case, fact.id, text=""), pack_id) == {"BLANK_TEXT"}
    assert codes(case.model_copy(update={"intro": " "}), pack_id) == {"BLANK_TEXT"}
    named = case.locations[0].model_copy(update={"description": ""})
    assert codes(case.model_copy(update={"locations": (named, *case.locations[1:])}), pack_id) == {
        "BLANK_TEXT"
    }


def test_a_suspect_without_traits_is_a_blank_text(pack_id):
    case = made(1, "standard", pack_id)
    bare_suspect = case.suspects[0].model_copy(update={"traits": ()})
    assert codes(
        case.model_copy(update={"suspects": (bare_suspect, *case.suspects[1:])}), pack_id
    ) == {"BLANK_TEXT"}


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda t: t + " {who}", "a stray brace"),
        (lambda t: t.replace(" ", "  ", 1), "two spaces"),
        (lambda t: t + " the the", "doubled word"),
        (lambda t: t + " a owl", "an article"),
    ],
)
def test_a_badly_rendered_text_is_reported(pack_id, change, problem):
    case = made(1, "standard", pack_id)
    issues = lint(case.model_copy(update={"intro": change(case.intro)}), pack_of(pack_id))
    assert {i.code for i in issues} == {"BAD_RENDER"} and problem in issues[0].message


def test_two_facts_with_the_same_sentence_are_reported_once(pack_id):
    case = made(1, "standard", pack_id)
    issues = lint(case.model_copy(update={"intro": case.facts[0].text}), pack_of(pack_id))
    assert [i.code for i in issues] == ["DUPLICATE_SENTENCE"] and issues[0].path == "intro"


def test_a_text_that_names_another_suspect_than_the_actor_fails_fidelity(pack_id):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    lie = first(case, FactKind.LIE)
    actor = next(s for s in case.suspects if s.id == lie.claim.actor)
    other = next(s for s in case.suspects if s.id != actor.id)
    mine, theirs = (phrase(slots.name_entry(pack, s)) for s in (actor, other))
    swapped = edit_fact(case, lie.id, text=lie.text.replace(mine, theirs))
    issues = lint(swapped, pack)
    assert {i.code for i in issues} == {"CLAIM_VALUE_MISSING"}
    assert issues[0].path == f"facts.{lie.id}.text"


def test_fidelity_follows_the_actor_of_a_lie_not_its_speaker(pack_id):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    lie = first(case, FactKind.LIE)
    other = next(s for s in case.suspects if s.id != lie.claim.actor)
    assert lint(edit_fact(case, lie.id, speaker=other.id), pack) == ()


@pytest.mark.parametrize("what", ["place", "time"])
def test_a_text_that_loses_its_place_or_time_fails_fidelity(pack_id, what):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    fact = first(case, FactKind.PRESENCE)
    assert fact.claim is not None
    place = next(x for x in case.locations if x.id == fact.claim.place)
    value = (
        phrase(slots.place_entry(pack, place))
        if what == "place"
        else (slots.slot_time(pack, fact.claim.slot)["time.at"])
    )
    assert value in fact.text
    broken = edit_fact(case, fact.id, text=fact.text.replace(value, "somewhere"))
    assert codes(broken, pack_id) == {"CLAIM_VALUE_MISSING"}


def test_a_value_must_stand_in_the_text_as_whole_words(pack_id):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    fact = first(case, FactKind.PRESENCE)
    place = next(x for x in case.locations if x.id == fact.claim.place)
    value = phrase(slots.place_entry(pack, place))
    assert codes(
        edit_fact(case, fact.id, text=fact.text.replace(value, value + "er")), pack_id
    ) == {"CLAIM_VALUE_MISSING"}


def test_a_lie_needs_a_contradiction_that_names_the_true_place(pack_id):
    case = made(1, "standard", pack_id)
    lie = first(case, FactKind.LIE)
    for bad in (None, "", "But that was not so."):
        assert codes(edit_fact(case, lie.id, contradiction=bad), pack_id) == {
            "CONTRADICTION_MISSING"
        }


def test_a_display_name_must_keep_the_distinctive_label_tokens(pack_id):
    case = made(1, "standard", pack_id)
    suspect = case.suspects[0]
    renamed = suspect.model_copy(update={"display_name": "A stranger"})
    broken = case.model_copy(update={"suspects": (renamed, *case.suspects[1:])})
    assert codes(broken, pack_id) == {"LABEL_NOT_IN_NAME"}


def distinctive_word(case, pack, method):
    """A raw word of the method's label whose stem is distinctive to it across the pack."""
    own = candidate_tokens(pack)[f"method:{method.type}"]
    definition = next(d for d in pack.method_defs if d.key == method.type)
    words = [w for text in (definition.label, *definition.aliases) for w in text.split()]
    return next(w for w in words if set(tokens(w)) & own)


def test_a_method_token_in_a_fact_that_does_not_touch_it_is_a_leak(pack_id):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    method = next(m for m in case.methods if m.id != case.truth.how)
    word = distinctive_word(case, pack, method)
    assert codes(case.model_copy(update={"intro": f"{case.intro} {word}"}), pack_id) == {
        "LEAK_TOKEN"
    }
    hint = first(case, FactKind.MOTIVE_CLUE)
    assert codes(edit_fact(case, hint.id, text=f"{hint.text} {word}"), pack_id) == {"LEAK_TOKEN"}


def test_a_method_token_in_a_fact_that_touches_the_method_is_allowed(pack_id):
    pack, case = pack_of(pack_id), made(1, "standard", pack_id)
    method = next(m for m in case.methods if m.id != case.truth.how)
    word = distinctive_word(case, pack, method)
    own = next(
        f
        for f in case.facts
        if f.kind is FactKind.ABSENT_TRACE and f.effects[0].candidate == method.id
    )
    assert codes(edit_fact(case, own.id, text=f"{own.text} {word}"), pack_id) == set()
    other = next(
        f
        for f in case.facts
        if f.kind is FactKind.ABSENT_TRACE and f.effects[0].candidate != method.id
    )
    assert codes(edit_fact(case, other.id, text=f"{other.text} {word}"), pack_id) == {"LEAK_TOKEN"}
