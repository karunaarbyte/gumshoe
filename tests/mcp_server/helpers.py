"""Shared pieces for the MCP server tests."""

from gumshoe.cases import Case, generate_case, load_builtin_pack
from gumshoe.mcp_server import GameHost


class SeqIds:
    """A pinned id source: 0000000000000001, 0000000000000002, ... (16 hex characters each)."""

    def __init__(self, start: int = 1) -> None:
        self.n = start

    def next(self) -> str:
        value = f"{self.n:016x}"
        self.n += 1
        return value


def make_host() -> GameHost:
    return GameHost(ids=SeqIds())


def castle_case(seed: int, preset: str = "standard") -> Case:
    """The same case `new_game(seed, preset)` makes, for tests that need the truth."""
    return generate_case(seed, preset, load_builtin_pack("castle"))


def explore_all(host: GameHost, game: str) -> None:
    """Search, question and read everything until nothing opens (a few rounds always suffice)."""
    brief = host.case_brief(game)
    for _ in range(6):
        for location in brief.locations:
            host.search(game, location.handle)
        for suspect in brief.suspects:
            host.interrogate(game, suspect.handle)
        for handle in [*(x.handle for x in brief.suspects), *(x.handle for x in brief.locations)]:
            host.check_records(game, handle)


def handle_named(host: GameHost, game: str, axis: str, name: str) -> str:
    return next(c.handle for c in host.nameable(game, axis).options if c.name == name)


def true_triple(host: GameHost, game: str, case: Case) -> tuple[str, str, str]:
    """The handles of the true culprit, method and motive (needs everything to be nameable)."""
    truth = case.truth
    who = next(s.display_name for s in case.suspects if s.id == truth.who)
    how = next(m.label for m in case.methods if m.id == truth.how)
    why = next(m.label for m in case.motives if m.id == truth.why)
    return (
        handle_named(host, game, "who", who),
        handle_named(host, game, "how", how),
        handle_named(host, game, "why", why),
    )
