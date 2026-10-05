# The generator's evidence stages (2d-2): design

Status: design, written 2026-10-05 after brainstorming, a feasibility prototype and one independent adversarial review (findings folded in).
Extends `2026-10-03-generator-2d-overview-design.md` (stage contract, contracts (a) to (g), retry design) and
`2026-10-04-pack-structure-and-generator-structure-design.md` (2d-1: streams, `GenContext`, roster, truth, timeline). Parent:
`2026-10-01-case-engine-design.md` (sections 2 to 4). Not committed: `docs/` is git-ignored and committed by hand.

Decided with the user: **one spec, three plans**, executed in order, each with its own review and merge: **2d-2a** (the roster
change and the facts stage), **2d-2b** (placement), **2d-2c** (gating, `build_case`, the end-to-end tests).

## 1. Intent

2d-1 produced the structure of a case: who is on the roster, what the truth is, where everyone is in every slot. 2d-2 adds the evidence:
the facts, where each fact can be found, and what gates it, and assembles a **skeleton-only `Case`** (every skin field blank, ids are the
neutral positions) that passes `validate(case, pack, STRICT)` with zero issues. No retry loop is involved: the design satisfies the validator
**by construction** on the castle (the retry controller of 2d-3 stays as a net for other packs).

Success criteria:
1. For every seed 0..199 and every claimed preset (short, standard, long) **and every feasible gating depth** (section 6), `build_case`
   returns a `Case` for which `validate(case, pack, STRICT)` reports no issue, and `skipped_groups == ()`.
2. On at least 10 seeds per preset in the default suite (more behind the `slow` marker in 2d-4) the simulator agrees: `judge(case)` reports
   every axis decidable, a single survivor and `can_win`.
3. Truth symmetry holds for everything a player can observe (section 8): equal fact counts per suspect, equal shapes per axis, equal
   decisive depths, and trivial classifiers on the placement features (keys, supports, lie places) score within chance + 3 sigma.
4. Output is byte-identical across processes with different `PYTHONHASHSEED`; golden digests pin the three new stage outputs for 5 seeds
   per preset.
5. `replay` runs and overrides the new stages; every override is checked against `ctx.spec` as in 2d-1.

Out of scope: skin, `skin_lint`, the permutation and final ids, the retry controller and `generate()` (2d-3); statistics at 1,000 seeds,
`explain`, difficulty tuning (2d-4); pack content (2c.1b) and pack-check hardening (section 10).

## 2. What the feasibility work established

A throwaway prototype (scratch worktree, not committed) built these facts on the 2d-1 outputs and ran the real validator and simulator:
zero strict issues on 600 fresh seeds per preset at every feasible depth (the reviewer ran 5,000 per preset on the earlier version);
the simulator was decidable, single-survivor and winnable on every case tried. Three findings shaped the design:
- **`short` fits the castle.** The overview's "search demand 10 against a cap of 9" assumed the who-evidence is searched. With the who-evidence
  in each suspect's record, search carries only the 2M how facts (6 of 9) and records carry 3S (12 of 12.8). No preset or pack change.
- **The culprit's who-proof cannot be "presence at the scene"**: opportunity suspects hold the same entry (overview contract (e)). The
  proof is a physical fact that mirrors the opportunity suspects' physical rule-out.
- **Every loop over suspects that touches shared state must run in a role-blind shuffled order.** Placing keys in canonical order (culprit
  first) made "the suspect whose key location has the fewest facts" find the culprit at 0.43 against a chance of 0.20.

## 3. The evidence shape

Every case has the same shape (values in this section are the castle's; counts follow from S suspects, M methods, L locations).
`s0`, `m0`, `v0` are the truth (2d-1); `O` is the timeline's opportunity set; `cp(k)` is suspect `k`'s crime-slot place; `rk(k)` is
`k`'s secret record kind (the roster's `record_kind`); `rec(k)` is the source `record(rk(k), k)`.

**Per suspect `k` (exactly 5 facts, so ownership is equal by construction):**

| Fact | Kind | Source | Effects | Condition |
|---|---|---|---|---|
| `sec_k` | SECRET | `rec(k)` | WHY `v_k`: `proves` if `k = s0`, else `rules_out` | all |
| `e_k` | PRESENCE | `rec(k)` | WHO `k`: `supports` | `k = s0` or `k in O` |
| `e_k` | ALIBI | `rec(k)` | WHO `k`: `rules_out` | `k` wrong and not in `O` |
| `x_k` | PHYSICAL | `rec(k)` | WHO `k`: `proves` if `k = s0`, else `rules_out` | `k = s0` or `k in O` |
| `w_k` | PRESENCE | `rec(k)` | WHO `k`: `supports` | `k` wrong and not in `O` |
| `y_k` | MOTIVE_CLUE | `interrogate(k)`, speaker `k` | WHY `v_k`: `supports` | all |
| `l_k` | LIE | `interrogate(k)`, speaker `k`, `truthful = false` | WHO `k`: `rules_out` (unexposed lies mislead) | all |

- `e_k` claims presence of `k` at `cp(k)` in the crime slot (`timeline_ref` = that event). `w_k` claims presence of `k` at their
  actual place in one non-crime slot, drawn among the slots whose place the record kind `rk(k)` attests (all slots if none does), with
  that event as `timeline_ref`.
- `l_k` claims presence of `k` at a place drawn uniformly among the chosen non-scene locations (`l1..`) **minus a decoy place**, in the
  crime slot (the decoy is `cp(k)` for an away suspect and, for an at-scene suspect, a draw among the non-scene locations their record kind
  attests, so the lie is never the true place and every suspect's lie has the same distribution; contract (h)). `exposed_by = (e_k,)` and `exposure_hook = rec(k)`: the suspect's own record contradicts their own lie.
- So a record always holds exactly three facts: the culprit's and an opportunity suspect's are {SECRET, PRESENCE, PHYSICAL}; a
  non-opportunity suspect's are {SECRET, ALIBI, PRESENCE}. **ALIBI and PRESENCE on a record source render with the same record-presence
  family** (2c.1b), so the only thing that separates the culprit from an opportunity suspect is the polarity of the physical text.
- Logic of the who axis: a suspect whose record puts them at the scene and carries a physical item is at the scene; the physical item is
  either incriminating (`proves`) or exculpating (`rules_out`); everyone elsewhere has an alibi. The culprit is the only suspect at the
  scene with no exculpation, and the proves-route is the incriminating item.

**Per method `m_j` (2 facts, owner none):**
- `h_mj`: TRACE (`j = 0`, `proves` HOW `m_j`) or ABSENT_TRACE (`j > 0`, `rules_out` HOW `m_j`), with a `trace_kind` of a trace of the
  method, found by searching a location whose kind is in that trace's `location_kinds`; **it requires `p_mj`** (the structural
  clue-before-trace dependency).
- `p_mj`: CLUE, `supports` HOW `m_j`, found by searching a **different** location from `h_mj`.

**Extras:** a neutral CLUE `n_<kind>` (no effects, no claim, owner none) on `record(kind, location)` for each chosen location-subject
record kind (the castle's `gate_log`), so the kind has a source; and, at gating depth 2, a neutral key CLUE `c_k` per suspect
(section 6). Fact counts: `T = 5S + 2M (+ S keys at depth 2) (+ 1 per location record)`; castle: 27 / 34 / 53.

**Shapes per axis** (the validator's `SHAPE_MISMATCH` counts source kind and decisive/supports): WHO `[(record, decisive), (record,
supports)]` for every suspect; HOW `[(search, decisive), (search, supports)]`; WHY `[(record, decisive), (interrogate, supports)]`.

**Properties kept on purpose.** (1) Lies are never required to be exposed (parent "no grind"); an unexposed lie rules its speaker out
in the player's gate, so a player who has not read the culprit's record can be steered to an unexamined innocent. This is the existing gate
design, documented here as an intended trap, not a defect. (2) A record can only be requested after its gate, so reading the culprit's
record is never free (section 6).

## 4. Stage 0: the roster change (plan 2d-2a)

2d-1's roster chose the K record kinds and then each suspect's secret kind independently, so about 20% of short and standard rosters leave
a chosen suspect-subject kind held by no suspect (a second record on some suspect would single them out). Change `roster.run` step 3:
choose the K-set and the secret kinds **together** so that **every chosen suspect-subject record kind is some suspect's secret kind**.
Algorithm (no product over all assignments, which is exponential in S): for each K-subset (sorted), let `Kd` be its suspect-subject kinds;
enumerate injective assignments of the kinds of `Kd` to distinct **holder roles** whose usable kinds include them (backtracking over at most
K kinds), skipping a subset where some role has no usable kind in it; the feasible list is the (subset, holders) pairs; `choice` one by
index; every other role takes `choice` among its usable chosen kinds from its child stream, as now. An empty list raises
`GenerationError`. This regenerates the 2d-1 goldens once: `STAGE_VERSIONS["roster"]` becomes 2, `SKELETON_ALGO_VERSION` becomes 2.

## 5. The facts stage (plan 2d-2a)

`generate/facts.py`, `stream("facts")` (its own stream; `STAGE_VERSIONS["facts"] = 1`). `run(ctx, stream, truth, timeline, depth=None) ->
FactsOut`. The `depth` argument exists for tests (force a feasible depth); `None` draws it.

1. **Depth.** Compute the feasible set `F` (section 6) and draw `depth` uniformly from it with `choice` over the sorted list. Empty `F`
   raises `GenerationError` saying the windows or the source capacity rule out every depth.
2. **Per suspect** (every draw uses a child stream keyed by the suspect position, so the facts stage touches no shared state and needs no
   shuffle; its output is in canonical order, so **placement and gating must iterate in a role-blind shuffled order**): the seven rows of
   section 3, with the `w` slot and the lie place drawn as stated.
3. **Per method** (a child stream per method position): choose a trace of the method uniformly among those whose kind is in `scene.allowed_trace_kinds` and
   that fit some chosen location, record its `trace_kind` and the **allowed location kinds** (`trace.location_kinds`) on the decisive fact.
4. **Extras:** the neutral location-record facts and, at depth 2, the keys (their sources are left to placement).

**`FactsOut`** (frozen, canonical digest, strings/ints/bools/tuples only, like the 2d-1 outputs): `depth`, `facts` (tuple of `FactDesc`),
`record_sources` (tuple of `(kind, subject_type, subject)` with `subject = None` for a location record, whose location placement picks).
`FactDesc`: `id` (neutral, lowercase, 2 to 32 characters: `sec_s0`, `e_s0`, `x_s0`, `w_s1`, `y_s2`, `l_s3`, `h_m0`, `p_m0`, `c_s4`,
`n_gate_log`), `kind` (a `FactKind` value), `effects` (tuples of axis, candidate position, effect kind), `claim` (`None` or a presence claim: actor
position, slot, place position; every claim here is presence), `truthful`, `speaker`, `exposed_by`, `exposure_hook` (a home), `timeline_ref` (event ids `e_<pos>_<slot>`),
`trace_kind`, `requires` (only `h_mj -> p_mj`), `home` (`record`/`interrogate`/`search` with `target` and `subject`; a search fact has no
subject yet) and `place_kinds` (for a search fact: the location kinds it may be found in; empty means any) and `apart_from` (a fact id whose
location it must differ from: `p_mj` has `h_mj`).

## 6. Gating depth and the placement stage

**Depth** `d` is one integer per case, **the same for every suspect**:
- `d = 0`: no gate.
- `d = 1`: `record(rk(k), k)` requires `y_k` (the suspect's own hint, obtained by questioning them).
- `d = 2`: additionally the suspect `k` requires the key `c_k` (a neutral search fact) before they can be questioned.

Per-suspect chains are disjoint, so the proves route and the elimination route of every axis share no gate fact, and removing any
single fact leaves every axis deducible (the validator's no-single-point-of-failure rule). The routes: WHO proves `x_s0`; WHY proves
`sec_s0`; HOW proves `h_m0` after `p_m0`.

**Feasibility set `F` (closed form; the plan tests it against the validator).** For `d`, the cheapest solution has size `4 + d`, depth
`max(1, d)` and at least `3` actions (`record(s0)`, `search` of `h_m0`, `search` of `p_m0`), at least `4` for `d >= 1` (adds
`interrogate(s0)`). `d` is feasible iff all hold: the preset's `solution` window contains `4 + d`, its `depth` window contains `max(1, d)`,
its `actions` window contains `3` (`d = 0`) or `4` (`d = 1`) or **both 4 and 5** (`d = 2`: the culprit's key may sit at a third location), and the decisive ratio holds (`300 <= decisive_pct_max * T(d)` with `T(d) = 5S + 2M + location records + (S if d = 2)`), and `L <= 2M` (every location needs a search fact), and capacity: with `cap = spec.source_cap` (4), search demand `2M + (S if
d = 2)` is at most `floor(0.8 * cap * L)` and at most `cap * L`, and record demand `3S + (location records)` is at most
`floor(0.8 * cap * (S + location records))`. On the castle this gives short `{0, 1}` (depth 2 breaks search capacity: 10 against 9),
standard `{0, 1, 2}` (at L = 4, depth 2 breaks it: 13 against 12), long `{2}` (depths 0 and 1 miss the size and depth windows).

**`generate/placement.py`**, `stream("placement")`. `run(ctx, stream, truth, facts) -> PlacementOut` (the timeline is not needed):
1. Search load per location starts at 0; the per-location cap is `spec.source_cap`.
2. Methods in a role-blind shuffled order: place each decisive `h_mj` at a location from its `place_kinds` with load below the cap, **least
   loaded first, ties by `choice`**.
3. Methods in a shuffled order: place each `p_mj` at the least loaded location below the cap that differs from `h_mj`'s.
4. Every location must hold a search fact. Clues take the least loaded location, so an empty location is always filled first; an
   empty location after step 3 means fewer facts than locations (`L <= 2M` prevents it) and raises `GenerationError`. (The first draft had a
   repair step that moves a clue into an empty location; the independent review showed it can never run.)
5. At depth 2: place the keys in a **role-blind shuffled suspect order**, each at the least loaded location below the cap, ties by `choice`.
6. Record sources: one per suspect, `(rk(k), suspect, k)`; for each chosen location-subject kind, a source at a location drawn among
   those whose kind is in the record's `location_kinds` (roster contract (g') guarantees one) and its neutral fact placed on it.
**`PlacementOut`**: `search` (tuple of `(fact id, location position)`), `record_sources`, the location chosen for each location record.

## 7. The gating stage and `build_case` (plan 2d-2c)

`generate/gating.py`, `stream("gating")`, `STAGE_VERSIONS["gating"] = 1`. Gating **only wires**; every fact already exists. `run(ctx,
stream, facts, placement) -> GatingOut`: `depth`; `suspect_requires` (`k -> c_k` at depth 2); `record_requires` (`(rk(k), k) -> y_k` at
depth >= 1); `start_locations` (all locations), `start_suspects` (all suspects without a requirement), `start_facts` (none). It checks
nothing the validator checks.

`generate/assemble.py`, `build_case(ctx, truth, timeline, facts, placement, gating) -> Case`: a skeleton-only `Case` with neutral position
ids (the final ids and the permutation are 2d-3's `assemble`), `origin` generated, `pack_ref`, the effective `spec`, the truth
`(s0, m0, v0)`, suspects (label and aliases from the roster, `secret_fact = sec_k`, `knows` = the facts they speak or are questioned
for, `requires` from gating), locations, record sources (with `requires`), methods and motives (label, aliases, type), the timeline (one
event per suspect and slot; the crime event is `s0`'s crime-slot cell), the facts (source from `home` or `placement`, `requires`). Skin
fields stay blank (the overview verified blank-skin cases validate identically).

## 8. Truth symmetry (contract (i), new)

- **Role-blind order.** Any loop over suspects or methods that places something in shared state (keys, search placement, ties) iterates in
  an order shuffled by a stream, never in canonical (culprit-first) order; draws that belong to one suspect use a child stream keyed by
  their position.
- **Equal by construction:** 5 facts per suspect, one lie, one exposure; shapes per axis; every candidate's decisive facts sit at the same
  depth (all records share `d`; HOW decisive facts have depth 1), so no candidate is ever the unique extreme and `CULPRIT_UNIQUE_EXTREME`
  and `TRUTH_DEPTH_EXTREME` cannot fire.
- **Contract (h) (replaces the open point):** every suspect's lie place is drawn uniformly among the chosen non-scene locations minus a
  **decoy** place that is drawn like an away suspect's crime place (attested by the suspect's record kind): the decoy is `cp(k)` for an away
  suspect and a draw among the attested non-scene locations for the culprit and opportunity suspects. Without the decoy, an away suspect's
  lie was unattested more often than an at-scene suspect's (0.886 against 0.944 in `short`, a culprit tell found by the second review).
- **Observable differences that remain are the intended deduction**: whether a suspect's record puts them at the scene (a physical item
  exists), and the polarity of the physical item.
- **Tests:** trivial classifiers on placement features (key location load, key sharing a location, supports location, lie place,
  `w` presence) over 1,500 seeds per preset must score within chance + 3 sigma (chance `1/S`).

## 9. Testing strategy

- **Validity:** for seeds 0..199, each preset, **each feasible depth** (forced through `facts.run(depth=...)`): zero issues from
  `validate(build_case(...), pack, STRICT)`. A negative test per rule family shows the harness can fail (swap `x_s0` to `supports`:
  `NO_POSITIVE_EVIDENCE` and `SHAPE_MISMATCH`; place a key in canonical order: the classifier test fails; remove `h`'s `requires`: actions
  window).
- **Closed form:** a test computes `F` per preset and checks it against the depths that validate (castle: short `{0,1}`, standard
  `{0,1,2}`, long `{2}`); capacity-forced emptiness raises `GenerationError`.
- **Invariants on the stage outputs:** per-suspect fact counts, shapes, every lie's exposer, the `w` attested preference, the placement cap
  and no empty location, the `p` apart from `h` rule, determinism, golden digests of `FactsOut`, `PlacementOut`, `GatingOut` for 5 seeds per
  preset, cross-process determinism.
- **Simulator agreement:** 10 seeds per preset in the default suite (about 10 s), 300 behind `slow` in 2d-4.
- **Roster change:** every chosen suspect-subject kind is some suspect's secret kind (every seed, every preset); a pack whose coverage is
  infeasible raises `GenerationError`; the 2d-1 goldens regenerate and `test_every_stage_has_a_version` covers the new versions.
- **Replay:** `run_structure` grows to all six stages (`STAGES = roster, truth, timeline, facts, placement, gating`); an override is
  checked against `ctx.spec` (as in 2d-1) and against the neighbouring outputs (a facts override must match the truth's suspects and methods).

## 10. Pack inputs, pack checks and follow-up plans

**Inputs 2c.1b must supply** (the castle has presence-record, alibi, trace, absent-trace, secret, motive-clue and the three lie families):
- `PRESENCE` and `ALIBI` facts on a record source render with the **same** record-presence family (the castle's `alibi` family is spoken
  hearsay).
- **Two `PHYSICAL` families on a record source**, method-agnostic and with no method token: an incriminating one (the culprit's proof) and an
  exculpating one (an opportunity suspect's rule-out); the polarity is the only difference between them.
- A neutral location-record entry family (`n_<kind>`), a key-clue family with a `{who}` slot (it unlocks a suspect), a per-motive hint
  family linking the hint to the motive, per-motive rule-out and per-method absent templates (an absent trace that names its place), the
  contradiction family, a victim and `intro` family **stating the scene and the crime slot** (the whole who deduction depends on them),
  the `smalltalk_allow` vocabulary and per-role persona style.

**Pack checks (a follow-up hardening plan, before 2e adds packs).** The stages raise `GenerationError` with a clear message when these
assumptions fail; the pack checks should catch them first: at least 3 locations; every scene has exactly one location kind; roles with at
least one name and enough distinct names across eligible roles; names equal after NFC; no duplicate keys inside a scene's lists; every
claimed preset has a feasible depth (the closed form of section 6); enough supports facts to fill every location (`L <= 2M`); every method
has a trace that fits the scene and a non-scene chosen location; suspect-kind coverage of the roster (section 4); record kind keys that
make valid neutral fact ids (`n_<kind>`: lowercase, at most 30 characters); no `event`-subject record kind (the stages only support suspect
and location subjects); the location enumeration budget. (These join the 2d-1 deferrals.)

## 11. Risks and open points

- **`short` sits on the capacity boundary** (depth 2 infeasible by one fact); a pack with fewer locations loses depths. The feasibility
  closed form makes that a clear error, and a pack check will make it a load-time rejection.
- **Same shape every case.** Variety comes from the roster, the timeline, placement and the depth (short 2 values, standard 3, long 1).
  Deeper variety is 2d-4's difficulty tuning.
- **The skeleton is constructed to pass the validator, so a validator change can break it.** The end-to-end tests are the guard; any new
  rule is a new test first.
- **`h_mj` requires `p_mj` is structural** (it raises the cheapest solution's action count to 4 without changing the presets); it is
  declared by the facts stage, which amends the overview's ownership table (gating owns every other `requires`).
- **The gate trap** of section 3 is documented, not designed away.
- **Deferred:** `Output.digest` omits the class name (decide before the 2d-4 pin); `build_pack` test fixture lacks nouns and names; the
  statistics at 1,000 seeds (2d-4).
