import time
from fractions import Fraction

from gumshoe.cases.simulate.blind import blind_guess_win_probability, guess_win_probability
from tests.cases.fixtures import build_case


def test_one_candidate_per_axis_always_wins():
    assert guess_win_probability([["a"], ["b"], ["c"]], ("a", "b", "c")) == 1


def test_two_triples_are_both_covered_by_three_attempts():
    assert guess_win_probability([["a", "x"], ["b"], ["c"]], ("a", "b", "c")) == 1


def test_four_indistinguishable_triples_win_three_in_four():
    # feedback never separates the wrong triples: 1/4 + 3/4 * (1/3 + 2/3 * 1/2) = 3/4
    assert guess_win_probability(
        [["a"], ["b"], ["c1", "c2", "c3", "c4"]], ("a", "b", "c1")
    ) == Fraction(3, 4)


def test_a_truth_outside_the_pool_never_wins():
    assert guess_win_probability([["x"], ["y"], ["z"]], ("a", "b", "c")) == 0


def test_two_by_two_by_two_with_count_only_feedback():
    assert guess_win_probability([["a", "x"], ["b", "y"], ["c", "z"]], ("a", "b", "c")) == Fraction(
        3, 4
    )


def test_the_fixture_read_through_then_guessed_wins_four_ninths_of_the_time():
    # every candidate holds a lead after reading everything, so all 27 triples are permitted
    assert blind_guess_win_probability(build_case()) == Fraction(4, 9)


def test_renaming_candidates_does_not_change_the_result():
    pools = [["a", "x", "y"], ["b", "z"], ["c", "w", "v", "u"]]
    renamed = [["q9", "a1", "zz"], ["m", "b0"], ["k", "c", "j", "e"]]
    assert guess_win_probability(pools, ("a", "b", "c")) == guess_win_probability(
        renamed, ("q9", "b0", "e")
    )
    # and a truth outside one axis's pool, under two namings
    assert guess_win_probability(pools, ("a", "nope", "c")) == guess_win_probability(
        renamed, ("zz", "b9", "j")
    )


def test_a_long_size_pool_is_computed_quickly():
    # 7 x 5 x 7 = 245 permitted triples (the `long` preset): took 14.5 s before canonicalising
    pools = [[f"w{i}" for i in range(7)], [f"h{i}" for i in range(5)], [f"y{i}" for i in range(7)]]
    started = time.perf_counter()
    p = guess_win_probability(pools, ("w3", "h1", "y6"))
    assert time.perf_counter() - started < 2
    assert p == Fraction(12, 245)  # the value the old exhaustive calculation gave
