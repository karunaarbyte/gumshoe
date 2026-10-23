from gumshoe.cases.play import GameSession
from gumshoe.cases.tools.play_cli import render_notebook, run_play
from tests.cases.fixtures import build_case


def play(inputs: list[str]) -> tuple[int, str]:
    """Run the game on scripted input; returns (exit code, everything printed)."""
    out: list[str] = []
    it = iter(inputs)

    def read(prompt: str) -> str:
        out.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    code = run_play(GameSession(build_case(), "salt"), read, out.append)
    return code, "\n".join(out)


def test_a_scripted_win_by_numbers():
    # 1 search -> The study (2); 3 records -> Boris (5) -> all kinds (1); 5 accuse -> 1,1,1 -> y
    code, text = play(["1", "2", "3", "5", "1", "5", "1", "1", "1", "y"])
    assert code == 0
    assert "Boris's monogrammed cufflink lies beside the body." in text
    assert "The ledger shows Boris owes a ruinous gambling debt." in text
    assert "3 of 3 right" in text and "You solved the case!" in text
    assert "poisoned in the wine" in text  # the reveal after the end


def test_typed_names_resolve_and_hedged_text_asks_again():
    script = ["1", "2", "3", "5", "1", "5", "it wasn't Boris", "Boris", "poison", "debt", "y"]
    code, text = play(script)
    assert code == 0 and "I can't tell which you mean" in text and "You solved the case!" in text


def test_a_locked_place_and_an_early_accusation_are_explained_not_fatal():
    code, text = play(["1", "3", "5", "q"])  # 3: the cellar
    assert code == 0
    assert "You can't get in there yet" in text
    assert "don't have enough to name anyone" in text
    assert "Goodbye" in text


def test_give_up_asks_first_then_reveals():
    code, text = play(["6", "y"])
    assert code == 0 and "The case is closed" in text and "Boris" in text


def test_declining_the_confirmation_withdraws_without_using_an_attempt():
    code, text = play(["1", "2", "3", "5", "1", "5", "1", "1", "1", "n", "q"])
    assert code == 0 and "Accusation withdrawn" in text and "3 attempts left" in text


def test_end_of_input_ends_politely():
    code, _ = play([])
    assert code == 0


def test_the_notebook_renders_sections_relations_and_contradictions():
    s = GameSession(build_case(), "salt")
    brief = s.brief()
    anna = next(x.handle for x in brief.suspects if x.name == "Anna")
    s.check_records(anna, "ledger")
    s.interrogate(anna)
    lines = render_notebook(s.notebook())
    text = "\n".join(lines)
    assert "Anna" in text and "[contradicted]" in text
    assert "Anna says the cellar, but the ledger places her in the garden." in text


def test_typed_names_only_match_what_the_player_may_name():
    # After only the study search, Anna is a real candidate but not nameable yet: typing her
    # must re-prompt (no probing); Boris, who is nameable, resolves.
    code, text = play(["1", "2", "5", "Anna", "1", "1", "q"])
    assert code == 0
    assert text.count("I can't tell which you mean") == 1
    assert "How was it done?" in text  # Boris was accepted on the who question


def test_keyboard_interrupt_ends_politely():
    def read(prompt: str) -> str:
        raise KeyboardInterrupt

    out: list[str] = []
    assert run_play(GameSession(build_case(), "salt"), read, out.append) == 0


def test_warnings_print_before_the_confirmation_prompt():
    session = GameSession(build_case(), "salt")
    brief = session.brief()
    for _ in range(2):
        for place in brief.locations:
            session.search(place.handle)
            session.check_records(place.handle, None)
        for person in brief.suspects:
            session.interrogate(person.handle)
            session.check_records(person.handle, None)
    out: list[str] = []
    it = iter(["5", "1", "1", "1", "n", "q"])  # Anna, poisoned in the wine, jealousy

    def read(prompt: str) -> str:
        out.append(prompt)
        return next(it)

    run_play(session, read, out.append)
    ask = out.index("(y/n) ")
    assert any("You hold an alibi or clue against Anna" in line for line in out[:ask])


def test_non_ascii_digits_re_prompt_instead_of_crashing():
    # '²'.isdigit() is True but int('²') raises; '١' (Arabic-Indic one) int()s to 1
    code, text = play(["1", "²", "١", "", "5", "q"])
    assert code == 0 and text.count("Pick one of the numbers above.") == 2
    code, text = play(["1", "2", "3", "5", "1", "5", "²", "١", "", "q"])
    assert code == 0 and text.count("I can't tell which you mean") == 2


def test_a_typed_method_the_player_may_not_name_yet_re_prompts():
    # after only the study search the rope is a real method but not nameable: typing it must
    # look like nonsense; the poison, which is nameable, resolves
    code, text = play(["1", "2", "5", "Boris", "the rope", "poison", "q"])
    assert code == 0
    assert text.count("I can't tell which you mean") == 1
    assert 'enough to name anyone for "Why was it done?"' in text
