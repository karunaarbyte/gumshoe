"""Random corruptions of a case, built with model_copy so they bypass validation on purpose."""

import random

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import Effect, SourceRef
from gumshoe.cases.model.enums import Axis, EffectKind, SourceKind


def corrupt(case: Case, rng: random.Random, smuggle: bool = False) -> Case:
    for _ in range(rng.randint(1, 5)):
        facts = list(case.facts)
        ids = [f.id for f in facts] + ["f_ghost", "s_ghost", "", "x" * 40, "L BAD"]
        index = rng.randrange(len(facts)) if facts else 0
        choice = rng.choice(
            [
                "requires",
                "effect",
                "truth",
                "slot",
                "drop_fact",
                "source",
                "speaker",
                "start",
                "exposed_by",
                "claim",
                "dupe",
                "spec",
                "flip",
                "cycle",
            ]
        )
        if choice == "requires" and facts:
            facts[index] = facts[index].model_copy(
                update={"requires": tuple(rng.sample(ids, rng.randint(0, 3)))}
            )
        elif choice == "effect" and facts:
            effect = Effect(
                axis=rng.choice(list(Axis)),
                candidate=rng.choice(ids),
                kind=rng.choice(list(EffectKind)),
            )
            facts[index] = facts[index].model_copy(update={"effects": (effect,)})
        elif choice == "truth":
            case = case.model_copy(
                update={
                    "truth": case.truth.model_copy(
                        update={rng.choice(["who", "how", "why"]): rng.choice(ids)}
                    )
                }
            )
        elif choice == "slot" and case.timeline:
            events = list(case.timeline)
            k = rng.randrange(len(events))
            events[k] = events[k].model_copy(update={"slot": rng.randint(-3, 99)})
            case = case.model_copy(update={"timeline": tuple(events)})
        elif choice == "drop_fact" and facts:
            facts.pop(index)
        elif choice == "source" and facts:
            source = SourceRef.model_construct(
                kind=rng.choice(list(SourceKind)),
                target=rng.choice(ids),
                subject=rng.choice([None, rng.choice(ids)]),
            )
            facts[index] = facts[index].model_copy(update={"source": source})
        elif choice == "speaker" and facts:
            facts[index] = facts[index].model_copy(update={"speaker": rng.choice([None, *ids])})
        elif choice == "start":
            case = case.model_copy(
                update={
                    "start": case.start.model_copy(
                        update={"facts": tuple(rng.sample(ids, rng.randint(0, 3))), "locations": ()}
                    )
                }
            )
        elif choice == "exposed_by" and facts:
            facts[index] = facts[index].model_copy(
                update={
                    "exposed_by": tuple(rng.sample(ids, rng.randint(0, 2))),
                    "truthful": rng.random() < 0.5,
                }
            )
        elif choice == "claim" and facts:
            facts[index] = facts[index].model_copy(update={"claim": None})
        elif choice == "dupe" and facts:
            facts.append(facts[index])
        elif choice == "flip" and facts:  # keeps group 1 clean: only flips a flag
            facts[index] = facts[index].model_copy(update={"truthful": not facts[index].truthful})
        elif choice == "cycle" and len(facts) > 1:  # keeps group 1 clean: valid ids only
            other = rng.choice([f.id for f in facts])
            facts[index] = facts[index].model_copy(update={"requires": (other,)})
        elif choice == "spec":
            case = case.model_copy(
                update={
                    "spec": case.spec.model_copy(
                        update={"slots": rng.randint(0, 6), "suspects": rng.randint(0, 5)}
                    )
                }
            )
        case = case.model_copy(update={"facts": tuple(facts)})
    if smuggle:  # wrong types on purpose: the validator must still return a report
        poison = rng.choice(["facts_none", "int_id", "non_fact", "none_suspects"])
        if poison == "facts_none":
            case = case.model_copy(update={"facts": None})
        elif poison == "int_id" and case.facts:
            first = case.facts[0].model_copy(update={"id": 7})
            case = case.model_copy(update={"facts": (first, *case.facts[1:])})
        elif poison == "non_fact":
            case = case.model_copy(update={"facts": (*case.facts, "not a fact")})
        else:
            case = case.model_copy(update={"suspects": None})
    return case
