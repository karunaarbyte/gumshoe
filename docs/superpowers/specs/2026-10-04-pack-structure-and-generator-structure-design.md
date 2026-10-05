# Pack inputs for structure (2c.1a) and the generator's structural stages (2d-1): combined design

Status: design, written 2026-10-04, revised after an independent review the same day. Implements the first two plans of the order set in
`2026-10-03-generator-2d-overview-design.md` (section 4); read that document first, its contracts and retry design bind this one. Also extends
`2026-10-02-pack-format-2c-design.md` (the pack format) and the parent `2026-10-01-case-engine-design.md` (sections 3 and 4). Not committed:
`docs/` is git-ignored and committed by hand.

The two plans are specified together because 2d-1 decides what the pack must carry. They are still **two plans, executed in order**: 2c.1a
first (pack and castle), then 2d-1 (generator), each with its own implementation plan, review and merge.

## 1. Intent

2c gave a validated castle pack. The generator's first stages (roster, truth, timeline) need things the pack does not yet say: how to write a
suspect's label ("Hugh the steward"), what a record kind is called and where it can attest a person to have been, and a guarantee that every
scene a preset can use has enough suspects whose records can attest it. 2c.1a adds them. 2d-1 then builds the stream machinery, the preset field
the later stages need, and the roster, truth and timeline stages, with golden digests, invariants and a structural probe against the real
validator.

Success criteria:
1. The pack checks reject a pack that lacks a role noun, a record display name or record location kinds, that has colliding role tokens, or
   whose scenes cannot host a claimed preset (too few hosting scenes); each new check has a mutation test with an exact cascade. The castle
   passes all of them.
2. `{record}` is a known placeholder bound to a record kind's display name; every hard-coded record name in the castle (the two families and
   the three `presence` pairs) is replaced by it, so truthful and lying record facts draw names from one pool by construction (2c hand-off item 2).
3. `PresetDef` and `Spec` carry `opportunity`; `derive_spec` copies it; `SPEC_MISMATCH` still holds.
4. For every seed 0..199 and every claimed preset the roster, truth and timeline stages produce outputs that satisfy contracts (a), (b), (c), (e),
   (f) of the overview and (g') of this spec as invariant tests, deterministically (byte-identical across `PYTHONHASHSEED`).
5. The **structural probe** passes (section 5): with the corrected stubs the validator reports `skipped_groups == (6, 8, 9)` and only issues
   from {EMPTY_LOCATION, NO_STATEMENT, OPPORTUNITY_NOT_RULED_OUT, UNTOUCHABLE_CANDIDATE}, for 200 seeds per preset; the probe is shown to fail
   on a broken timeline.
6. Golden digests of the three outputs for 5 seeds per preset pin the stages; `replay` returns any stage's output and accepts an override.

Out of scope: facts, placement, gating, assemble, skin, the retry controller, `generate()` (2d-2 onwards); the evidence pack inputs of 2c.1b;
the `supports` (`r`) preset field (2d-2 adds it with its consumer, regenerating the goldens then; no consumer exists in 2d-1).

## 2. Plan 2c.1a: pack inputs for structure

### 2.1 Model additions (`model/pack.py`)

| Addition | Meaning |
|---|---|
| `RoleDef.noun: str` | display noun of the role ("steward"). A suspect's label is `"<name> the <noun>"`, its aliases are `<name>` and `the <noun>` (these derived aliases are the "spoken forms" of the parent spec) |
| `RecordDef.names: tuple[Entry, ...]` | display names of the record kind (`Entry(text="household register", article="the")`); the first is used by `{record}`. Wording: **not** in `skeleton_view` |
| `RecordDef.location_kinds: SetTexts` | the kinds of place this record kind can attest (2.2). Skeleton: in `skeleton_view` |

All default to empty so existing `Pack(...)` calls keep working; the checks of 2.4 make them required (the new stage-5 codes are
**unconditional**: they apply to every pack, with or without `presets`). `Pack.skeleton_view` gains each role's `noun` and each record kind's
`location_kinds`; its domain tag becomes `gumshoe.pack.skeleton.v3`. Record `presence` lines stay in the pack (2c.1b decides their fate) but now use
`{record}`.

### 2.2 What `location_kinds` means

- For a **suspect-subject** record kind (visitor ledger, household register): the location kinds where a suspect can be recorded as present.
- For a **location-subject** record kind (gate log): the location kinds it is about.

A record about a suspect that "attests" a place is what exposes a lie: the culprit's own record shows where they really were.

### 2.3 The `{record}` placeholder

`{record}` renders the first display name with its article ("the household register"); `{^record}` capitalises. It joins
`lint.KNOWN_PLACEHOLDERS`; both lint `SAMPLES` and the pool-derived `pack_sample` get a `record` value (otherwise renders drop it to the empty
string and skew the length-parity test). **Binding:** `{record}` is the display name of the record kind of the fact's source or claim, decided
in skin (2d-3). Scope of the guarantee: with every hard-coded record name in `presence_record`, `lie_record` and the three
`record_defs.*.presence` pairs replaced by `{record}`, a record name can only come from `{record}`, so truth and lie cannot differ by record name.
The families keep their voice shapes (3 impersonal, 2 third-party, 2 self-report each: variants 6 and 7 name no book, so a pure substitution
preserves them). The castle test of parity is updated accordingly.

### 2.4 New pack checks

| Check | Stage and code | Rule |
|---|---|---|
| role noun present | stage 5, `ROLE_NO_NOUN` (new) | every role has a non-empty `noun` |
| role token collisions | stage 4, `ROLE_TOKEN_COLLISION` (new) | (i) two roles may not share a token of their nouns; (ii) no token of a role noun or of any role **name** equals a token of any method or motive label or alias (**all** tokens, not only distinctive ones, as the validator's `LABEL_NAME_COLLISION` does: a noun like "look-out" collides with every "out of ..." motive label) |
| record names present | stage 5, `RECORD_NO_NAME` (new) | every record kind has at least one display name |
| record location kinds present | stage 5, `RECORD_NO_LOCATION_KIND` (new) | every record kind lists at least one location kind |
| record location kinds exist | stage 2, existing `UNKNOWN_LOCATION_KIND` | each listed kind is a defined location kind |
| record names are pool text | stage 3 and 4, existing codes | record names join `lint.pool_items` (stage 3 pool lints) and `hygiene._texts` (leak scan) |
| presets can be hosted | stage 6, existing `PRESET_UNSUPPORTED` | see below |

**Usable kind, eligible role, hosting scene.** A record kind is **usable for a scene** when its subject is `suspect`, it lists the scene's location
kind, **and it lists at least one other location kind** (so a role can be placed away from the scene, contract (b')). A role is **eligible for a
scene** when it has a usable kind. A scene **hosts a preset** when it allows at least `spec.methods` methods **and** has at least `spec.suspects`
eligible roles. A preset needs at least `MIN_HOSTING_SCENES` (3) hosting scenes. This replaces the methods-only count of the stage-6 rule added in 2c
(one shared function in `packs/check/capacity.py` serves the check and roster step 1). The reason keeps the existing format:
`hosting scenes=2 (needs at least 3)`. **Deviation from the overview's (b):** the overview asks every scene to leave enough eligible roles; only
*hosting* scenes matter (a scene that cannot hold `long`'s five methods need not hold seven roles).

New pack codes: 34 plus 4 (`ROLE_NO_NOUN`, `ROLE_TOKEN_COLLISION`, `RECORD_NO_NAME`, `RECORD_NO_LOCATION_KIND`) is 38; the golden catalogue and
the mutation table are updated (one mutation per code, exact cascades). **Hidden work:** `tests/packs/fixtures.py` (`BASE_TOML`, `rich_pack`) and,
if pack-checked, `tests/cases/fixtures.build_pack` need nouns, record names and `location_kinds`, or every existing mutation cascade changes.
Role names stay distinct by the castle test only (no pack code): the roster draws distinct names.

### 2.5 Castle content (user decision: option A)

With the castle's role `record_kinds` (chapel register: cook, falconer, groom, priest, bard, clerk, maid; visitor ledger: steward, bard, clerk,
maid), the numbers are: eligible roles per scene are 8 when both kinds attest it, 7 when only the chapel register does, 4 when only the visitor
ledger does. Standard (5 suspects) therefore needs the chapel register in every scene it can host, which is all seven. **Option A:** keep every role's
record kinds; `chapel_register.location_kinds` lists **all 7** location kinds and its display name becomes **"the household register"** (everyone
signs it wherever they are), which makes the breadth plausible. The key stays `chapel_register`. The visitor ledger lists most rooms (not the
undercroft, not the herb garden; the plan fixes the list, subject to the constraint that every hosting scene keeps at least the preset's suspect
count); the gate log (location-subject) lists `gatehouse`. Display names: "the visitor ledger", "the household register", "the gate log".

Chunks, each shown to the user before the next (as in 2c): (1) the 8 role nouns and the pack-model/check changes with their tests; (2) record display
names and `location_kinds`; (3) the `{record}` rewrite of the two families and the three `presence` pairs. The plan reports, before and after, the
hosting-scene count per preset and the eligible-role count per scene.

## 3. Plan 2d-1: the generator's structural stages

### 3.1 The preset field (`model/spec.py`, `model/entities.py`, `model/roles.py`)

`PresetDef` and `Spec` gain one required integer, `opportunity`: how many **wrong** suspects can reach the scene in the crime slot (user decision):

| Preset | opportunity |
|---|---|
| short | 1 |
| standard | 2 |
| long | 3 |

A `PresetDef` model validator enforces `0 <= opportunity <= suspects.min - 1` (a `SizeRange` has a min and a max); `Spec` has `Field(ge=0)`;
`check_presets` stays for table-level problems. `derive_spec` copies it. `schema_version` stays 1 (no case has been saved yet; the 2a goldens are
regenerated). **Blast radius (grepped):** 6 `PresetDef(` constructions (3 in `PRESETS`, `tests/cases/fixtures.py:424`,
`tests/cases/model/test_spec.py:105`, `tests/packs/fixtures.py:117`), 5 `Spec(` constructions (`spec.py:139`, `tests/cases/fixtures.py:283`,
`tests/cases/model/builders.py:34`, `tests/cases/model/test_case.py:97/98`), the `FIELD_ROLES` table (skeleton; guarded by the
every-field-classified test), the goldens `tests/cases/golden/manor_small.*` (also read by `test_determinism.py`). `custom_spec`'s opportunity is 1
(the fixture has one wrong suspect at the scene). No validator rule reads `Spec.opportunity`; only the generator invariants do.

### 3.2 `generate/streams.py`

A **sha256 counter-mode** generator. Byte stream: block `i` is
`sha256(DOMAIN || canonical_json([seed, spec_hash, stage_version, counter, label]) || i.to_bytes(8, "big"))`, with `DOMAIN` a fixed tag; `child(label)`
derives from the **key**, never from the parent's position. Primitives accept only sequences (a set or frozenset raises `TypeError`):
- `below(n)`: `n <= 0` raises, `n == 1` returns 0 without consuming; otherwise draws a u64 per attempt and rejects `x >= 2**64 - 2**64 % n`
  (no modulo bias).
- `shuffle(seq)`: Fisher-Yates; `sample(seq, k)`: partial Fisher-Yates on a copy, returning an ordered sample; `choice(seq)`: `seq[below(len)]`.
- `rank(keys, label)`: rendezvous hashing: each key scored by `sha256(DOMAIN || label || key)`, ties broken by the key itself; the top-k by score is
  the pool sample (parent 4.8).
`streams.py` imports no `random`; `hashlib` is allowed by the determinism rule, so the `streams.py` exemption in `tests/test_architecture.py` is
**removed** (no loophole left). No floats. Golden values pin every primitive.

### 3.3 `generate/gen_context.py`

Frozen `GenContext`: pack, presets mapping, the effective `Spec` (`derive_spec`), seed, preset name, `spec_hash` (sha256 of the canonical JSON of the
`Spec`), `STAGE_VERSIONS` (`roster=1,truth=1,timeline=1`) and `SKELETON_ALGO_VERSION = 1`. `GenContext.of` raises a clear error when the preset is
not in `capacity.hosted_specs(pack, presets)` (the pack checks exclude presets `derive_spec` alone would accept).

### 3.4 The stage outputs

Frozen Pydantic models (the project's `Frozen`): ints, strings, bools and tuples of them, no floats, each with `digest()` from `canonical_json`.
Entities carry **neutral pool positions** (`"s0"`, `"m1"`, `"v2"`, `"l0"`), never final ids; the permutation comes in 2d-3.
- `RosterOut`: `scene_type` (pack key); `suspects` (`RosterSuspect(pos, name, role, noun, label, aliases, motive_pos, record_kind)`, where
  `record_kind` is the suspect's **secret record kind**, owned by the roster; the overview's ownership table is amended accordingly);
  `methods` (`pos, key, label, aliases`); `motives` (`pos, key, label, aliases`); `locations` (`pos, kind, decorative=False`; **`l0` is the scene**);
  `record_kinds` (the K chosen pack keys). There is no separate matching field: `motive_pos` is the matching. The roster is **not** a `Case`.
- `TruthOut`: the roster reordered so the culprit is `s0`, the true method `m0`, and (V = S) the culprit's motive `v0`, positions renumbered;
  `why_pos == "v0"`. Later stages may treat `s0`, `m0`, `v0` as the truth and no other position specially.
- `TimelineOut`: `crime_slot`, `rows` (for every suspect and every slot, the location pos: the **table of every suspect's place in every slot**),
  `opportunity` (the wrong suspects at the scene in the crime slot). The culprit's crime-slot cell is the crime event (action `crime`); every
  other cell is a `present` event. The scene is `l0`.

`SceneType.location_kinds` is a tuple: v1 requires exactly one kind per scene (castle test; the roster uses `location_kinds[0]` as "the scene kind").

### 3.5 The roster stage (`stream("roster")`)

Pool samples use **rendezvous `rank`** (parent 4.8: pool sampling is by rendezvous hashing, never file order; the overview says the parent wins);
enumerated choices (K-set, matching) use `choice` over a **sorted** list (`Pack.known_record_kinds` is a frozenset: sort before enumerating).
1. **Scene.** Among the preset's **hosting scenes** (2.4), pick one by `rank`.
2. **Roles and names.** Take the top `spec.suspects` eligible roles by `rank`; for each, the top-1 name from its pool by `rank`, skipping a name already
   used (names are distinct across the roster). Label `"<name> the <noun>"`, aliases `(<name>, "the <noun>")`.
3. **Record kinds.** Enumerate the K-subsets (K = `spec.record_kinds`) of the sorted record kinds such that **every chosen role has at least one
   chosen usable kind** (contracts (a), (b)); `choice` one. Each suspect's `record_kind` is a `choice` among that role's chosen usable kinds.
4. **Methods.** Top `spec.methods` of the scene's `allowed_methods` by `rank` (each has a trace placeable at the scene: pack check of 2c).
5. **Motives.** Enumerate the roster's valid suspect-to-motive matchings (the pack's `matchings`, within its budget) and `choice` one by index.
6. **Locations.** Enumerate the `(spec.locations - 1)`-subsets of the non-scene location kinds that satisfy all of: (c) every chosen method has a
   **non-scene** chosen location inside its trace's `location_kinds`; (b') every chosen role has a **non-scene** chosen location inside its suspect's
   `record_kind`'s `location_kinds`; (g') every chosen **location-subject** record kind has a chosen location inside its `location_kinds`
   (otherwise contract (f) could only be met by breaking the meaning of `location_kinds`); `choice` one. `l0` is the scene kind. Enumeration (at most
   15 subsets for the castle) replaces rejection: no loop cap, no re-draw wording, no bias question; the 2c.1a pack check makes the enumeration non-empty
   for every reachable draw on the castle (the plan verifies it exhaustively, scene x roles x K-set x methods).
If any enumeration is empty the stage raises a clear `GenerationError` (it cannot happen on a pack that passes the checks).

### 3.6 The truth stage (`stream("truth")`)

`below(S)` for the culprit, `below(M)` for the true method; reorder suspects, methods and motives (V = S: the culprit's motive is `v0`) and renumber
positions. The culprit is uniform over the roster because it is drawn **independently after** the roster, so the roster's conditioning (steps 3 and 6)
cannot leak the truth through role, scene or method distributions. The truth stage does not read the timeline.

### 3.7 The timeline stage (`stream("timeline")`)

1. `crime_slot` is `choice` among slots `1 .. slots-2` (two values for 4 slots; a slot before and after remain for alibis and witnesses).
2. The culprit is at the scene (`l0`) in the crime slot. Exactly `spec.opportunity` wrong suspects, chosen by `sample`, are also there.
3. Every other suspect is placed in the crime slot at a `choice` among the chosen non-scene locations inside their `record_kind`'s `location_kinds` (always
   non-empty by (b')).
4. In every other slot every suspect's place is a `choice` among all chosen locations; rows are independent between suspects (parent 3); one place per
   suspect per slot, so no double-booking by construction.
5. The table of rows is part of the output (contract (e)), so later truthful witness claims (which require co-location) never need the timeline redrawn.
Note for 2d-2 (contract (h), new): a liar's claimed crime-slot place should come from the same distribution as the places innocents are actually
recorded at (attested non-scene), or a claimed place no record of that kind could attest would mark the culprit; the 2d-2 spec fixes this. Under the
castle's broad `location_kinds` (option A) the tell is vacuous, but it must hold for other packs.

### 3.8 `replay`

`src/gumshoe/cases/tools/gen_dev.py`: `replay(seed, preset, pack, upto, override=None)` runs the stages in order (counter 0 in 2d-1; the retry
controller is 2d-3), stops after `upto` and returns the outputs so far; `override={stage: output}` replaces a stage's output and re-runs only the later
stages. `tools/` only; the player-surface architecture test (which already restricts what `play_cli` may import) is extended to prove it is unreachable
from `play`.

## 4. Contracts as invariants

Tests against the stage outputs, not by reusing validator rule functions:

| Contract | Test |
|---|---|
| (a) record kinds vs roles | every role has a chosen usable kind; exactly `spec.record_kinds` kinds are chosen |
| (b), (b') symmetric attestation | every suspect's `record_kind` attests the scene kind and at least one non-scene chosen location; every suspect's crime-slot place is attested by it |
| (c) trace locations | every chosen method has a non-scene chosen location inside its trace's `location_kinds`; every trace kind is in `scene.allowed_trace_kinds` |
| (g') location-subject kinds | every chosen location-subject kind has a chosen location inside its `location_kinds` |
| (e) timeline table | every suspect x every slot present once; the culprit at the scene in the crime slot; exactly `opportunity` wrong suspects there |
| (f) record kinds are used | probe: one stub source per chosen kind keeps `COUNT_MISMATCH(record_kinds)` silent |
| symmetry | over 200 seeds per preset, goodness of fit of the culprit's (role, motive) per cell (expected count = sum over cases of 1[pair present] / S, cells with expected count >= 5), with a Bonferroni-corrected threshold fixed in the plan; plus uniformity of the culprit's pre-reorder roster position, which tests `below` only. Note: on the castle the culprit-motive marginal is exactly 1/8 because every motive is allowed by 5 roles, a property of this pack |
| determinism | byte-identical outputs across processes with different `PYTHONHASHSEED`; golden stage digests for 5 seeds per preset |

(d) is section 3.1. (g) belongs to 2d-2.

## 5. The structural probe (test-only)

`tests/generate/probe.py` builds a partial `Case` from the three outputs, using the corrected stub design (the spec-literal stubs the review tried
produced SECRET_SOURCE_MISMATCH and SOURCE_CAP_EXCEEDED, and a secret on an undeclared source makes a group-1 error that skips everything and passes trivially):
suspects, methods, motives, locations, one `Event` per suspect per slot (the crime event in the culprit's crime-slot cell), the truth, `spec`,
`scene_type`, `pack_ref`, **one record source `(suspect.record_kind, suspect)` per suspect holding that suspect's stub `SECRET` fact** (the parent: "one
record per suspect, record(kind, that suspect)"), **plus one stub source for every chosen record kind not otherwise used** (a location subject for a
location-subject kind, inside its `location_kinds`), and `start` with everything. It runs `validate(case, pack, STRICT)` and asserts
`report.skipped_groups == (6, 8, 9)` **and** that the issue codes are a subset of {EMPTY_LOCATION, NO_STATEMENT, OPPORTUNITY_NOT_RULED_OUT,
UNTOUCHABLE_CANDIDATE}. A negative test shows the probe fails when it should (a timeline with the culprit off the scene gives CULPRIT_NO_OPPORTUNITY). The
issues that remain belong to later stages.

## 6. Testing strategy

- **2c.1a:** one mutation per new pack code with an exact cascade (existing table and golden catalogue, 38 codes); the changed stage-6 hosting rule gets
  its own mutations (a pack with 2 hosting scenes; a scene with too few eligible roles); castle tests extended (nouns distinct and non-empty; every record kind
  has names and location kinds; hosting-scene count per preset and eligible roles per scene meet the preset; `{record}` used in the two families and the
  presence pairs and no hard-coded record name left; one location kind per scene); every new test shown able to fail.
- **2d-1:** streams (golden values for every primitive, independence between labels, set rejection, uniformity of `below` on small ranges, `child` independent of
  position), `GenContext` errors (unhosted preset), each stage's invariants over seeds 0..199 per preset, golden digests (5 seeds per preset), determinism across
  processes, the probe and its negative test, `replay` round trips and overrides, an infeasible pack raising `GenerationError`.
- The default suite stays fast; the 0..199 loops are cheap (each stage is a few draws and a bounded enumeration).
- **For the learner:** the 2d-1 plan includes one worked roster draw for `short` (scene, roles, K-set, methods, matching, locations) with the enumeration lists.

## 7. Risks and open points

- **Content plausibility:** option A makes the household register attest every room; the display name carries the plausibility. If a future pack cannot
  do this, the hosting check reports the shortfall.
- **The roster draws conditionally.** The roster's marginals over (scene, roles, methods) are not uniform over all combinations, only over feasible ones;
  the truth is drawn afterwards and independently, so this is not a leak of the culprit (shown in 3.6), but it is a property the 2d-4 statistics must account for.
- **The probe is only as strong as its stubs.** It proves the three stages cause no roster, truth or timeline code, not that 2d-2 can succeed; contracts (c),
  (e), (g'), (h) guard that.
- **Golden churn.** Changing `Spec` regenerates the 2a goldens and the fixture hashes once; adding `supports` in 2d-2 does it again.
- **Open for the plan:** the exact visitor-ledger `location_kinds` list; the symmetry test threshold; the number of stub sources per kind.
- **Deferred:** the evidence pack inputs (2c.1b) and contract (h) (2d-2 spec).
