"""The truth stage: the culprit and the true method, drawn after and apart from the roster."""

from gumshoe.cases.generate.gen_context import GenContext
from gumshoe.cases.generate.outputs import RosterOut, TruthOut
from gumshoe.cases.generate.streams import Stream


def _renumber(roster: RosterOut, culprit: int, method: int) -> RosterOut:
    """Move the culprit, the true method and the culprit's motive to index 0, keep the rest in
    order, and rename every position to its new index."""
    suspects = [
        roster.suspects[culprit],
        *(s for i, s in enumerate(roster.suspects) if i != culprit),
    ]
    methods = [roster.methods[method], *(m for i, m in enumerate(roster.methods) if i != method)]
    old_motive = roster.suspects[culprit].motive_pos
    first = next(m for m in roster.motives if m.pos == old_motive)
    motives = [first, *(m for m in roster.motives if m.pos != old_motive)]
    motive_pos = {m.pos: f"v{i}" for i, m in enumerate(motives)}
    return roster.model_copy(
        update={
            "suspects": tuple(
                s.model_copy(update={"pos": f"s{i}", "motive_pos": motive_pos[s.motive_pos]})
                for i, s in enumerate(suspects)
            ),
            "methods": tuple(m.model_copy(update={"pos": f"m{i}"}) for i, m in enumerate(methods)),
            "motives": tuple(m.model_copy(update={"pos": motive_pos[m.pos]}) for m in motives),
        }
    )


def run(ctx: GenContext, stream: Stream, roster: RosterOut) -> TruthOut:
    culprit = stream.below(len(roster.suspects))
    method = stream.below(len(roster.methods))
    return TruthOut(roster=_renumber(roster, culprit, method))
