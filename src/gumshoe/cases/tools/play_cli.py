"""The terminal game. This is a player surface: it sees only GameSession and the views."""

from collections.abc import Callable

from gumshoe.cases.play import (
    AxisProblem,
    GameSession,
    NotebookView,
    ParsedAccusation,
    SourceResult,
)

Read = Callable[[str], str]
Write = Callable[[str], None]

QUESTIONS = (("who", "Who did it?"), ("how", "How was it done?"), ("why", "Why was it done?"))


def run_play(session: GameSession, read: Read, write: Write) -> int:
    try:
        return _loop(session, read, write)
    except (EOFError, KeyboardInterrupt):
        write("")
        return 0


def _loop(session: GameSession, read: Read, write: Write) -> int:
    write(session.brief().intro)
    while session.status == "playing":
        write("")
        write("1) Search a place  2) Question someone  3) Check records")
        write("4) Notebook  5) Accuse  6) Give up  q) Quit")
        choice = read("> ").strip().lower()
        if choice == "1":
            _search(session, read, write)
        elif choice == "2":
            _question(session, read, write)
        elif choice == "3":
            _records(session, read, write)
        elif choice == "4":
            for line in render_notebook(session.notebook()):
                write(line)
        elif choice == "5":
            _accuse(session, read, write)
        elif choice == "6":
            if read("Give up and see the truth? (y/n) ").strip().lower() == "y":
                session.give_up()
        elif choice == "q":
            write("Goodbye.")
            return 0
        else:
            write("Choose 1-6 or q.")
    _ending(session, write)
    return 0


def _number(raw: str, count: int) -> int | None:
    """A menu number 1..count as a zero-based index, else None. ASCII digits only: '²' passes
    isdigit() and then int() raises, and '١' would int() to 1."""
    if raw.isascii() and raw.isdecimal() and 1 <= int(raw) <= count:
        return int(raw) - 1
    return None


def _pick(read: Read, write: Write, title: str, labels: list[str]) -> int | None:
    """A numbered menu: returns the zero-based choice, or None for blank/0/invalid-then-blank."""
    write(title)
    for n, label in enumerate(labels, start=1):
        write(f"  {n}. {label}")
    while True:
        raw = read("Number (blank to go back): ").strip()
        if raw in ("", "0"):
            return None
        picked = _number(raw, len(labels))
        if picked is not None:
            return picked
        write("Pick one of the numbers above.")


def _show_result(result: SourceResult, write: Write) -> None:
    if result.status == "locked":
        write("You can't get in there yet.")
        return
    if result.status == "unknown":
        write("There is no such thing here.")
        return
    if result.status == "nothing_new":
        write("Nothing new here.")
    for fact in result.new_facts:
        who = f"{fact.speaker}: " if fact.speaker else ""
        mark = " [contradicted]" if fact.contradicted else ""
        write(f"  - {who}{fact.text}{mark}")
    for item in result.contradictions:
        write(f"  !! {item.text}")
    if result.opened:
        write(f"New leads: {', '.join(result.opened)}")


def _search(session: GameSession, read: Read, write: Write) -> None:
    places = session.brief().locations
    labels = [f"{p.name}{' (locked)' if p.locked else ''}" for p in places]
    picked = _pick(read, write, "Search where?", labels)
    if picked is not None:
        _show_result(session.search(places[picked].handle), write)


def _question(session: GameSession, read: Read, write: Write) -> None:
    people = session.brief().suspects
    labels = [f"{p.name}{' (locked)' if p.locked else ''}" for p in people]
    picked = _pick(read, write, "Question whom?", labels)
    if picked is not None:
        _show_result(session.interrogate(people[picked].handle), write)


def _records(session: GameSession, read: Read, write: Write) -> None:
    brief = session.brief()
    subjects = [
        *((p.name, p.handle) for p in brief.locations),
        *((p.name, p.handle) for p in brief.suspects),
    ]
    picked = _pick(read, write, "Records about what or whom?", [name for name, _ in subjects])
    if picked is None:
        return
    kinds = [None, *brief.record_kinds]
    which = _pick(
        read, write, "Which records?", ["All kinds", *(k.label for k in brief.record_kinds)]
    )
    if which is None:
        return
    kind = kinds[which]
    result = session.check_records(subjects[picked][1], None if kind is None else kind.key)
    _show_result(result, write)
    if result.kinds:
        write(f"({', '.join(result.kinds)})")


def render_notebook(view: NotebookView) -> list[str]:
    if not view.sections:
        return ["Your notebook is empty."]
    lines: list[str] = []
    for section in view.sections:
        lines.append(f"{section.source}:")
        for fact in section.facts:
            who = f"{fact.speaker}: " if fact.speaker else ""
            about = f" (about {', '.join(fact.relates_to)})" if fact.relates_to else ""
            mark = " [contradicted]" if fact.contradicted else ""
            lines.append(f"  - {who}{fact.text}{about}{mark}")
    for item in view.contradictions:
        lines.append(f"!! {item.text}")
    return lines


def _collect(session: GameSession, read: Read, write: Write) -> ParsedAccusation | None:
    chosen: dict[str, str] = {}
    for axis, question in QUESTIONS:
        options = session.nameable(axis).options
        if not options:
            write(f'You don\'t have enough to name anyone for "{question}" yet.')
            return None
        write(question)
        for n, option in enumerate(options, start=1):
            note = "  (you hold something against this one)" if option.warned else ""
            write(f"  {n}. {option.name}{note}")
        while True:
            raw = read("Number or name (blank to cancel): ").strip()
            if not raw:
                return None
            picked = _number(raw, len(options))
            if picked is not None:
                chosen[axis] = options[picked].handle
                break
            handle = session.match_label(axis, raw)
            if handle is not None and handle in {o.handle for o in options}:
                chosen[axis] = handle
                break
            write("I can't tell which you mean. Choose a number from the list.")
    return ParsedAccusation(**chosen)


def _show_problems(problems: tuple[AxisProblem, ...], write: Write) -> None:
    for problem in problems:
        names = ", ".join(o.name for o in problem.options) or "nobody yet"
        write(f"On '{problem.axis}' you may name: {names}.")


def _accuse(session: GameSession, read: Read, write: Write) -> None:
    parsed = _collect(session, read, write)
    if parsed is None:
        return
    plan = session.describe_accusation(parsed)
    if plan.repeat:
        write("You already tried that.")
        return
    if not plan.can_confirm:
        _show_problems(plan.problems, write)
        return
    for warning in plan.warnings:
        write(warning)
    write(plan.confirmation)
    if read("(y/n) ").strip().lower() != "y":
        write(f"Accusation withdrawn. You still have {session.attempts_left} attempts left.")
        return
    write(session.accuse(parsed, confirmed=True).message)


def _ending(session: GameSession, write: Write) -> None:
    write("")
    write("You solved the case!" if session.status == "won" else "The case is closed.")
    truth = session.reveal()
    write(f"It was {truth.culprit}, {truth.method}, {truth.motive}.")
    if truth.secret:
        write(truth.secret)
