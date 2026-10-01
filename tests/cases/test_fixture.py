from pathlib import Path

from gumshoe.cases.core.ids import is_valid_id
from gumshoe.cases.model.enums import Axis, EffectKind, SourceKind
from gumshoe.cases.model.serialize import dump_case, load_case, skeleton_digest
from gumshoe.cases.model.spec import derive_spec
from tests.cases.fixtures import TINY_PRESETS, build_case, build_pack, build_strict_case

DATA = Path(__file__).parent / "golden"


def test_entity_counts():
    case = build_case()
    assert [
        len(x)
        for x in (
            case.suspects,
            case.methods,
            case.motives,
            case.locations,
            case.record_sources,
            case.timeline,
            case.facts,
        )
    ] == [3, 3, 3, 3, 5, 3, 22]
    assert case.truth.model_dump() == {"who": "s_boris", "how": "m_poison", "why": "v_debt"}


def test_all_ids_are_valid_and_unique():
    case = build_case()
    ids = [
        e.id
        for group in (
            case.suspects,
            case.locations,
            case.methods,
            case.motives,
            case.timeline,
            case.facts,
        )
        for e in group
    ]
    assert len(ids) == len(set(ids)) == 3 + 3 + 3 + 3 + 3 + 22
    assert all(is_valid_id(i) for i in ids)


def test_sources_hold_at_most_four_facts_and_the_expected_distribution():
    case = build_case()
    counts: dict[tuple[str, str, str | None], int] = {}
    for fact in case.facts:
        key = (fact.source.kind.value, fact.source.target, fact.source.subject)
        counts[key] = counts.get(key, 0) + 1
    assert max(counts.values()) == 4
    assert counts[("search", "l_study", None)] == 4
    assert counts[("search", "l_garden", None)] == 2
    assert counts[("search", "l_cellar", None)] == 1
    assert counts[("record", "gate_log", "l_study")] == 3
    assert counts[("record", "gate_log", "l_garden")] == 3
    assert sum(v for k, v in counts.items() if k[0] == "interrogate") == 6


def test_shape_per_axis_is_symmetric():
    case = build_case()
    shapes: dict[tuple[Axis, str], list[tuple[str, str]]] = {}
    for fact in case.facts:
        if not fact.truthful:
            continue
        for effect in fact.effects:
            decisive = (
                "decisive"
                if effect.kind in (EffectKind.RULES_OUT, EffectKind.PROVES)
                else "supports"
            )
            shapes.setdefault((effect.axis, effect.candidate), []).append(
                (fact.source.kind.value, decisive)
            )
    for axis in Axis:
        per_candidate = [sorted(v) for (a, _), v in shapes.items() if a is axis]
        assert len(per_candidate) == 3 and all(s == per_candidate[0] for s in per_candidate), axis


def test_each_suspect_has_exactly_one_lie_exposed_by_their_own_record():
    case = build_case()
    lies = [f for f in case.facts if not f.truthful]
    assert sorted(str(f.speaker) for f in lies) == ["s_anna", "s_boris", "s_clara"]
    for lie in lies:
        (exposer_id,) = lie.exposed_by
        exposer = next(f for f in case.facts if f.id == exposer_id)
        assert (
            exposer.truthful
            and exposer.source.kind is SourceKind.RECORD
            and exposer.source.subject == lie.speaker
        )
        assert lie.exposure_hook == exposer.source


def test_matches_the_committed_snapshot_and_digest():
    case = build_case()
    assert dump_case(case) == (DATA / "manor_small.json").read_bytes()
    assert skeleton_digest(case) == (DATA / "manor_small.digest").read_text().strip()
    assert load_case((DATA / "manor_small.json").read_bytes()) == case


def test_strict_variant_has_a_derived_spec_and_a_matching_pack_ref():
    pack, case = build_pack(), build_strict_case()
    assert case.spec == derive_spec("tiny", pack, TINY_PRESETS)
    assert case.pack_ref is not None and case.pack_ref.id == pack.id
    assert case.pack_ref.skeleton_hash == pack.skeleton_hash()
    assert skeleton_digest(case) != skeleton_digest(build_case())  # preset name differs
