"""Random scripted play: no event, no decider state and no persona prompt may carry a raw id, a
truth field, an unfound secret, or the true method or motive before the player has earned it."""

import random

import pytest

from gumshoe.agent.events import Clarify, Confirm, GameOver, ToolResult
from tests.agent.fakes import Script, ScriptedLlm
from tests.agent.harness import playing, press, turn
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


async def earned_text(h) -> str:
    """Everything the player may see by now: the brief, the held facts and the names the
    accusation gate lets them use. The true method or motive may appear only inside this."""
    game = h.ctx.game
    brief = await h.deps.client.case_brief(game)
    notebook = await h.deps.client.notebook(game)
    held = [f.text for s in notebook.sections for f in s.facts]
    nameable = [c.name for axis in ("how", "why") for c in h.host.nameable(game, axis).options]
    return "\n".join([brief.model_dump_json(), *held, *nameable])


def check(text: str, where: str, *, ids, unheld, secret_names, earned) -> None:
    assert not [i for i in ids if i in text], f"a raw id reached {where}"
    assert not [f for f in FIELDS_THAT_MEAN_TRUTH if f in text], f"a truth field reached {where}"
    assert not [t for t in unheld if t and t in text], f"an unfound secret reached {where}"
    for name in secret_names:  # one by one: two of the three must not slip through either
        assert name not in text or name in earned, f"the unearned {name!r} reached {where}"


@pytest.mark.parametrize("preset", ["short", "standard", "long"])
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_random_turns_leak_nothing(seed, preset):
    rng = random.Random(seed * 17 + len(preset))
    case = castle_case(seed, preset)
    ids = raw_ids(case)
    truth = case.truth
    # the culprit's name is public (every suspect is listed), so only how and why are secret
    secret_names = (
        next(x.label for x in case.methods if x.id == truth.how),
        next(x.label for x in case.motives if x.id == truth.why),
    )
    script = Script()
    llm = ScriptedLlm(["I was around.", "Hmm.", "Ask someone else."] * 60)
    async with playing(script, llm, seed=seed, preset=preset) as h:
        targets = [f"place_{x.number}" for x in h.brief.locations] + [
            f"suspect_{x.number}" for x in h.brief.suspects
        ]
        # the first turn voices a suspect when one is open (on long all start locked), so a
        # persona prompt is always checked on short and standard
        reachable = next((f"suspect_{x.number}" for x in h.brief.suspects if not x.locked), None)
        shown: str | None = None  # the last confirmation's id, as a UI would hold it
        seen_states = seen_prompts = 0
        for step in range(30):
            if shown is not None and rng.random() < 0.2:
                events = await press(h, shown, rng.choice(["yes", "no"]))
            else:
                first = step == 0 and reachable is not None
                script.understand(
                    intent="interrogate" if first else rng.choice(INTENTS),
                    target=reachable if first else rng.choice(targets + ["none"]),
                    weight=rng.choice([0.0, 3.0]),
                    confirm=rng.choice([None, 0.95, 0.05, 0.5]),
                )
                script.post_check()
                script.parse(who=None, how=None, why=None)
                script.parse(who=None, how=None, why=None)
                sent = shown if rng.random() < 0.5 else None
                events = await turn(h, f"turn {step}", pending_id=sent)
            confirms = [e for e in events if isinstance(e, Confirm)]
            if confirms:
                shown = confirms[-1].pending_id
            over = any(isinstance(e, GameOver) for e in events)
            notebook = await h.deps.client.notebook(h.ctx.game)
            held = {f.text for s in notebook.sections for f in s.facts}
            unheld = [s.secret_text for s in case.suspects if s.secret_text not in held]
            earned = await earned_text(h)
            seen = {"ids": ids, "unheld": unheld, "secret_names": secret_names, "earned": earned}
            blob = "".join(e.model_dump_json() for e in events if not is_the_reveal(e))
            plain = "".join(
                e.model_dump_json()
                for e in events
                if not is_the_reveal(e) and not echoes_an_accusation(e)
            )
            check(blob, f"the events at step {step}", **{**seen, "secret_names": ()})
            check(plain, f"the plain events at step {step}", **seen)
            for node, state, _ in h.decider.calls[seen_states:]:
                check(state, f"a {node} state at step {step}", **seen)
            for _, system, messages in h.llm.calls[seen_prompts:]:
                check(system, f"a persona prompt at step {step}", **seen)
                for message in messages:
                    check(message.content, f"a persona message at step {step}", **seen)
            seen_states, seen_prompts = len(h.decider.calls), len(h.llm.calls)
            if over:
                break
        # leftover scripted answers are fine: the script is a menu, not a transcript
    assert seen_states > 0  # the loop really looked at the decider's input
    assert seen_prompts > 0 or reachable is None  # and at the persona's
