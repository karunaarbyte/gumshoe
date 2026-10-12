"""persona_brief: what an agent may say in a suspect's voice, built only from what is held.

Pure and deterministic. The brief has the same shape for every suspect, the culprit included, and
it never reads a lie's claim, a secret or a truth field: `says` is the held facts found by
questioning this suspect, so a lie appears only once the player holds it, next to the suspect's
other statements and with nothing to tell it apart.
"""

from gumshoe.cases.model.entities import SourceRef
from gumshoe.cases.model.enums import SourceKind
from gumshoe.cases.model.index import CaseIndex
from gumshoe.cases.play.state import PlayState
from gumshoe.cases.play.views import PersonaBrief


def persona_brief(ix: CaseIndex, state: PlayState, suspect_id: str, name: str) -> PersonaBrief:
    suspect = ix.suspects[suspect_id]
    source = SourceRef(kind=SourceKind.INTERROGATE, target=suspect_id)
    held = state.held
    says = sorted(f.text for f in ix.facts_at(source) if f.id in held)
    return PersonaBrief(
        name=name,
        traits=suspect.traits,
        style=suspect.style,
        says=tuple(says),
        smalltalk_allow=tuple(ix.case.smalltalk_allow),
    )
