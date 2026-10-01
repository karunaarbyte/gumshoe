from gumshoe.cases.validate.report import Profile
from gumshoe.cases.validate.runner import validate
from tests.cases.fixtures import build_case
from tests.cases.helpers import replace_fact, replace_in
from tests.cases.mutations import MUTATIONS


def g07(case):
    return [i for i in validate(case, profile=Profile.CUSTOM).issues if i.group == 7]


def issues(code):
    case = MUTATIONS[code].apply(build_case())
    return [i for i in g07(case) if i.code == code]


def test_fixture_timeline_is_clean():
    assert g07(build_case()) == []


def test_double_booking_names_actor_slot_and_places():
    (issue,) = issues("DOUBLE_BOOKED")
    assert issue.subjects == ("s_anna",) and dict(issue.params) == {
        "places": "l_garden,l_study",
        "slot": "2",
    }


def test_two_events_for_one_actor_in_the_same_place_are_fine():
    case = build_case().model_copy(
        update={
            "timeline": (
                *build_case().timeline,
                build_case().timeline[0].model_copy(update={"id": "t_same"}),
            )
        }
    )
    assert "DOUBLE_BOOKED" not in {i.code for i in g07(case)}


def test_the_culprit_must_be_at_the_scene_in_the_crime_slot():
    (issue,) = issues("CULPRIT_NO_OPPORTUNITY")
    assert issue.subjects == ("s_boris",) and issue.spoiler


def test_an_innocent_with_opportunity_needs_a_truthful_reachable_rule_out():
    (issue,) = issues("OPPORTUNITY_NOT_RULED_OUT")
    assert issue.subjects == ("s_clara",)


def test_a_lie_that_ruled_out_the_innocent_does_not_count_as_a_rule_out():
    case = replace_fact(
        build_case(), "f_clara_keys", effects=()
    )  # only the lie rules Clara out now
    assert any(i.code == "OPPORTUNITY_NOT_RULED_OUT" for i in g07(case))


def test_truthful_claims_with_no_timeline_event_are_not_flagged_but_lies_without_evidence_are():
    case = replace_in(
        build_case(), "timeline", "t_anna_2", actor="s_clara"
    )  # no event for Anna at slot 2 now
    codes = {i.code for i in g07(case)}
    assert "CLAIM_CONTRADICTS_TIMELINE" not in codes
    assert "LIE_CONSISTENT_WITH_TIMELINE" in codes  # Anna's lie can no longer be shown false


def test_crime_events_are_counted_by_action_name():
    assert {i.code for i in g07(MUTATIONS["NO_CRIME_EVENT"].apply(build_case()))} == {
        "NO_CRIME_EVENT"
    }
    assert {i.code for i in g07(MUTATIONS["MULTIPLE_CRIME_EVENTS"].apply(build_case()))} == {
        "MULTIPLE_CRIME_EVENTS"
    }


def test_the_crime_event_must_be_the_culprits_even_if_the_culprit_is_also_at_the_scene():
    from gumshoe.cases.model.entities import Event

    case = replace_in(
        build_case(), "timeline", "t_crime", actor="s_clara"
    )  # Clara did it, per the events
    case = case.model_copy(
        update={
            "timeline": (
                *case.timeline,
                Event(id="t_boris_2", slot=2, actor="s_boris", place="l_study", action="present"),
            )
        }
    )
    assert "CULPRIT_NO_OPPORTUNITY" in {i.code for i in g07(case)}
