import pytest

from gumshoe.cases import UnknownHandle, dump_case, generate_case, load_builtin_pack, load_session
from gumshoe.cases.model.enums import FactKind, SourceKind

SALT = "salt-persona"


def castle_case(seed):
    return generate_case(seed, "standard", load_builtin_pack("castle"))


def session_for(case):
    return load_session(dump_case(case), SALT)


def suspect_handle(session, name):
    return next(s.handle for s in session.brief().suspects if s.name == name)


def names(case):
    return {s.id: s.display_name for s in case.suspects}


def lie_of(case, suspect_id):
    return next(
        f
        for f in case.facts
        if f.kind is FactKind.LIE
        and f.source.kind is SourceKind.INTERROGATE
        and f.source.target == suspect_id
    )


def test_before_questioning_a_suspect_says_nothing_and_has_their_voice():
    case = castle_case(1)
    session = session_for(case)
    for suspect in case.suspects:
        brief = session.persona_brief(suspect_handle(session, suspect.display_name))
        assert brief.name == suspect.display_name
        assert brief.traits == suspect.traits and brief.style == suspect.style
        assert brief.says == () and brief.smalltalk_allow == tuple(case.smalltalk_allow)


def test_after_questioning_says_holds_exactly_what_the_interrogation_returned_sorted():
    case = castle_case(1)
    session = session_for(case)
    suspect = case.suspects[0]
    handle = suspect_handle(session, suspect.display_name)
    result = session.interrogate(handle)
    brief = session.persona_brief(handle)
    assert brief.says == tuple(sorted(f.text for f in result.new_facts))
    assert len(brief.says) == len(result.new_facts) > 0


def test_the_suspects_lie_appears_verbatim_among_their_statements_only_once_held():
    case = castle_case(1)
    session = session_for(case)
    for suspect in case.suspects:
        handle = suspect_handle(session, suspect.display_name)
        lie = lie_of(case, suspect.id)
        assert lie.text not in session.persona_brief(handle).says
        session.interrogate(handle)
        says = session.persona_brief(handle).says
        assert lie.text in says and len(says) > 1  # next to the suspect's other statements


def test_questioning_one_suspect_does_not_change_anothers_brief():
    case = castle_case(1)
    session = session_for(case)
    a, b = case.suspects[0], case.suspects[1]
    before = session.persona_brief(suspect_handle(session, b.display_name))
    session.interrogate(suspect_handle(session, a.display_name))
    assert session.persona_brief(suspect_handle(session, b.display_name)) == before


def test_every_suspect_has_the_same_fields_and_the_culprit_is_not_special():
    case = castle_case(1)
    session = session_for(case)
    briefs = {
        s.id: session.persona_brief(suspect_handle(session, s.display_name)) for s in case.suspects
    }
    shapes = {tuple(b.model_dump()) for b in briefs.values()}
    assert len(shapes) == 1
    culprit = briefs[case.truth.who]
    assert tuple(culprit.model_dump()) == shapes.pop()


def test_no_secret_text_ever_reaches_a_brief():
    case = castle_case(1)
    session = session_for(case)
    for suspect in case.suspects:
        session.interrogate(suspect_handle(session, suspect.display_name))
    for suspect in case.suspects:
        brief = session.persona_brief(suspect_handle(session, suspect.display_name))
        for other in case.suspects:
            assert other.secret_text not in brief.model_dump_json()


def test_the_brief_before_the_lie_is_held_ignores_the_lies_claim_and_text():
    case = castle_case(1)
    other_place = next(loc.id for loc in case.locations)
    changed_facts = []
    for fact in case.facts:
        if fact.kind is FactKind.LIE and fact.claim is not None:
            claim = fact.claim.model_copy(update={"place": other_place})
            fact = fact.model_copy(update={"claim": claim, "text": "A different claim."})
        changed_facts.append(fact)
    changed = case.model_copy(update={"facts": tuple(changed_facts)})
    a, b = session_for(case), session_for(changed)
    for suspect in case.suspects:
        handle_a = suspect_handle(a, suspect.display_name)
        handle_b = suspect_handle(b, suspect.display_name)
        assert a.persona_brief(handle_a) == b.persona_brief(handle_b)


@pytest.mark.parametrize("handle", ["", "h_nothing"])
def test_an_unknown_handle_raises_unknown_handle(handle):
    with pytest.raises(UnknownHandle):
        session_for(castle_case(1)).persona_brief(handle)


def test_a_location_handle_is_not_a_suspect():
    session = session_for(castle_case(1))
    with pytest.raises(UnknownHandle):
        session.persona_brief(session.brief().locations[0].handle)


def test_the_brief_is_available_after_the_game_ends():
    case = castle_case(1)
    session = session_for(case)
    session.give_up()
    assert session.persona_brief(suspect_handle(session, case.suspects[0].display_name)).name
