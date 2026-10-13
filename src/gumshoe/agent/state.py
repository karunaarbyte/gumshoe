"""The `state` text sent to the decider: built from play views only, never from the truth.

The player's message comes first (the decision log keeps only the first 200 characters).
"""

from collections.abc import Sequence

from gumshoe.agent.config import AgentConfig
from gumshoe.cases import NotebookFact, NotebookView, PlayerCaseView


def cap_facts(notebook: NotebookView, cap: int) -> list[NotebookFact]:
    """Every contradicted fact plus the last `cap` facts, in notebook order. Sections sort by
    source label, so the same sources are always cut first; accepted and documented."""
    facts = [fact for section in notebook.sections for fact in section.facts]
    recent = {f.handle for f in facts[-cap:]}
    return [f for f in facts if f.contradicted or f.handle in recent]


def build_state(
    *,
    text: str,
    pending_line: str | None,
    exchanges: Sequence[tuple[str, str]],
    brief: PlayerCaseView,
    notebook: NotebookView,
    config: AgentConfig,
) -> str:
    lines = [f"Player says: {text}"]
    if pending_line:
        lines.append(f"Waiting for the player to confirm: {pending_line}")
    kept = exchanges[len(exchanges) - config.exchanges_kept :] if config.exchanges_kept else []
    for said, outcome in kept:
        lines.append(f"Earlier the player said: {said}")
        lines.append(f"What happened: {outcome}")
    lines.append("Places the player can search:")
    for place in brief.locations:
        lock = " (locked)" if place.locked else ""
        lines.append(f"  place_{place.number}: {place.name}{lock}")
    lines.append("Suspects the player can question:")
    for suspect in brief.suspects:
        lock = " (locked)" if suspect.locked else ""
        lines.append(f"  suspect_{suspect.number}: {suspect.name}{lock}")
    facts = cap_facts(notebook, config.notebook_cap)
    if facts:
        lines.append("Facts the player has found:")
        lines.extend(f"  {fact.text}" for fact in facts)
    return "\n".join(lines)
