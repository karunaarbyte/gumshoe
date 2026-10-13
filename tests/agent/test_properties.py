"""Random scripted play: no event may carry a raw id, a truth field or an unfound secret."""

import random

import pytest

from gumshoe.agent.events import Clarify, Confirm, GameOver, ToolResult
from tests.agent.fakes import Script, ScriptedLlm
from tests.agent.harness import playing, turn
from tests.mcp_server.helpers import castle_case
from tests.mcp_server.test_properties import FIELDS_THAT_MEAN_TRUTH, raw_ids


def echoes_an_accusation(event):
    """The events that may repeat the player's own accusation (or list what may be named), and
    the reveal."""
    return (
        isinstance(event, Confirm)
        or (isinstance(event, Clarify) and event.reason == "accusation")
        or (isinstance(event, ToolResult) and event.tool == "accuse")
    )


def is_the_reveal(event):
    """A game over, or the give_up result that carries the same reveal."""
    return isinstance(event, GameOver) or (
        isinstance(event, ToolResult) and event.tool == "give_up"
    )


INTENTS = [
    "search",
    "interrogate",
    "records",
    "talk",
    "notebook",
    "meta",
    "other",
    "accuse",
    "give_up",
]


@pytest.mark.parametrize("preset", ["short", "standard", "long"])
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_random_turns_leak_nothing(seed, preset):
    rng = random.Random(seed * 17 + len(preset))
    case = castle_case(seed, preset)
    ids = raw_ids(case)
    truth = case.truth
    truth_names = (
        next(x.display_name for x in case.suspects if x.id == truth.who),
        next(x.label for x in case.methods if x.id == truth.how),
        next(x.label for x in case.motives if x.id == truth.why),
    )
    script = Script()
    llm = ScriptedLlm(["I was around.", "Hmm.", "Ask someone else."] * 60)
    async with playing(script, llm, seed=seed, preset=preset) as h:
        targets = [f"place_{x.number}" for x in h.brief.locations] + [
            f"suspect_{x.number}" for x in h.brief.suspects
        ]
        for step in range(30):
            intent = rng.choice(INTENTS)
            target = rng.choice(targets + ["none"])
            script.understand(
                intent=intent,
                target=target,
                weight=rng.choice([0.0, 3.0]),
                confirm=rng.choice([None, 0.95, 0.05, 0.5]),
            )
            script.post_check()
            script.parse(who=None, how=None, why=None)
            script.parse(who=None, how=None, why=None)
            events = await turn(h, f"turn {step}")
            over = any(isinstance(e, GameOver) for e in events)
            blob = "".join(e.model_dump_json() for e in events if not is_the_reveal(e))
            assert not [i for i in ids if i in blob], f"a raw id reached the events at step {step}"
            assert not [f for f in FIELDS_THAT_MEAN_TRUTH if f in blob]
            plain = "".join(
                e.model_dump_json()
                for e in events
                if not is_the_reveal(e) and not echoes_an_accusation(e)
            )
            assert not all(n in plain for n in truth_names), "the true triple reached the events"
            notebook = await h.deps.client.notebook(h.ctx.game)
            held = {f.text for s in notebook.sections for f in s.facts}
            unheld = [s.secret_text for s in case.suspects if s.secret_text not in held]
            assert not [t for t in unheld if t and t in blob], (
                "an unfound secret reached the events"
            )
            if over:
                break
        # leftover scripted answers are fine: the script is a menu, not a transcript
