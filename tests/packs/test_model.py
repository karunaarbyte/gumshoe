import os
import subprocess
import sys
from pathlib import Path

from gumshoe.cases.model.pack import (
    Capacity,
    Entry,
    FamilyDef,
    LocationDef,
    MethodDef,
    Pack,
    RecordDef,
    RoleDef,
    TraceDef,
)
from tests.packs.fixtures import CAPACITY, rich_pack

ROOT = Path(__file__).resolve().parents[2]


def test_a_pack_with_only_the_old_fields_still_builds():
    capacity = Capacity(max_suspects=1, max_locations=1, max_methods=1, max_record_kinds=1)
    pack = Pack(id="x", capacity=capacity)
    assert pack.location_defs == () and pack.presets == () and pack.families == ()
    assert len(pack.skeleton_hash()) == 64


def test_the_hash_ignores_wording_and_skin_revision():
    base = rich_pack().skeleton_hash()
    fam = FamilyDef(
        id="alibi",
        kind="alibi",
        claim_slots=("who",),
        variants=("{^who} was seen.", "A second wording of the same claim: {who}."),
    )
    assert rich_pack(families=(fam,)).skeleton_hash() == base  # variants are wording
    assert rich_pack(skin_rev=9).skeleton_hash() == base
    trace = TraceDef(kind="residue", location_kinds=("study",), templates=("Different words.",))
    method = MethodDef(
        key="poison", label="poisoned in the wine", aliases=("poison",), traces=(trace,)
    )
    assert rich_pack(method_defs=(method,)).skeleton_hash() == base  # trace wording


def _changed(**changes):
    return rich_pack(**changes).skeleton_hash()


def test_the_hash_changes_with_structure_and_pool_membership():
    base = rich_pack().skeleton_hash()
    role = rich_pack().roles[0]
    names = (Entry(text="Maud", pronoun="she", proper=True), Entry(text="Gwen"))
    renamed = role.model_copy(update={"names": names})
    assert _changed(roles=(renamed,)) != base  # a new name joins the pool
    fam = FamilyDef(
        id="alibi", kind="alibi", claim_slots=("who", "place.in"), variants=("{^who} {place.in}.",)
    )
    assert _changed(families=(fam,)) != base  # a new claim slot
    method = rich_pack().method_defs[0]
    extra = method.model_copy(
        update={"traces": (*method.traces, TraceDef(kind="fibre", location_kinds=("study",)))}
    )
    assert _changed(method_defs=(extra,)) != base  # a new trace kind
    assert _changed(capacity=CAPACITY.model_copy(update={"max_suspects": 4})) != base
    assert _changed(presets=("tiny", "short")) != base


def test_lists_that_are_sets_are_sorted_but_text_lists_keep_their_order():
    method = MethodDef(key="m", label="l", aliases=("b", "a"))
    assert method.aliases == ("a", "b")
    entry = rich_pack().location_defs[0].model_copy(update={"descriptions": ("zeta", "alpha")})
    assert entry.descriptions == ("zeta", "alpha")


def test_known_record_kinds_unions_the_names_and_the_definitions():
    pack = rich_pack(record_kinds=("gate_log",))
    assert pack.known_record_kinds == frozenset({"gate_log", "ledger"})


def test_definitions_are_sorted_by_key_so_file_order_never_matters():
    a, b = LocationDef(key="a"), LocationDef(key="b")
    assert rich_pack(location_defs=(b, a)) == rich_pack(location_defs=(a, b))


def test_the_hash_is_identical_across_hash_seeds():
    script = "from tests.packs.fixtures import rich_pack; print(rich_pack().skeleton_hash())"
    digests = set()
    for seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        digests.add(result.stdout.strip())
    assert len(digests) == 1


def test_a_role_noun_and_record_location_kinds_change_the_hash_but_record_names_do_not():
    base = rich_pack()
    role = base.roles[0].model_copy(update={"noun": "housekeeper"})
    assert rich_pack(roles=(role,)).skeleton_hash() != base.skeleton_hash()
    record = base.record_defs[0]
    wider = record.model_copy(update={"location_kinds": (*record.location_kinds, "cellar")})
    assert rich_pack(record_defs=(wider,)).skeleton_hash() != base.skeleton_hash()
    renamed = record.model_copy(update={"names": (Entry(text="big book", article="the"),)})
    assert rich_pack(record_defs=(renamed,)).skeleton_hash() == base.skeleton_hash()


def test_the_new_pack_fields_default_to_empty_so_old_packs_still_build():
    pack = Pack(
        id="x",
        capacity=Capacity(max_suspects=1, max_locations=1, max_methods=1, max_record_kinds=1),
        roles=(RoleDef(key="r"),),
        record_defs=(RecordDef(key="k", subject="suspect", medium="written"),),
    )
    assert pack.roles[0].noun == ""
    assert pack.record_defs[0].names == () and pack.record_defs[0].location_kinds == ()


def test_record_location_kinds_are_a_sorted_set():
    record = RecordDef(key="k", subject="suspect", medium="written", location_kinds=("b", "a"))
    assert record.location_kinds == ("a", "b")
