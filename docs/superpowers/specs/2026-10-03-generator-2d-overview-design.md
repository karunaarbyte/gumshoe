# The case generator (sub-project 2d): overview design

Status: design, written 2026-10-03, revised twice after two independent reviews (2026-10-03 and 2026-10-04). Extends
`2026-10-01-case-engine-design.md` (section 3 "the generator", 3.7, 6.2) and inherits the hand-off list in
`2026-10-02-pack-format-2c-design.md` section 11. Not committed: `docs/` is git-ignored and committed by hand.

This document is the **overview**: architecture, the stage contract, the retry design, the cross-stage contracts, the split into plans, testing
and risks. It deliberately does not fix the detailed design of the evidence stages (facts, placement, gating); each sub-plan gets its own spec,
written against what the previous plan actually produced. Where this overview and the parent spec disagree, section 7 says which wins.

## 1. Intent

2a to 2c built everything around a case: the model, a validator (81 codes), a playable engine with a simulator, and a validated castle pack.
Nothing produces a case yet. 2d adds `generate(seed, preset, pack, presets=PRESETS) -> Case`: a pure, deterministic function that turns a
seed and the castle into a case that passes the strict validator and the simulator, whose truth cannot be guessed from structure.

Success criteria (from the parent spec, sections 3 and 6.2, sharpened by review):
1. For every seed 0..999 and every preset the castle claims (short, standard, long), `generate` returns a case that passes
   `validate(case, pack, STRICT)` and the simulator. "Passes the simulator" means `judge(case)` reports every axis decidable
   (`decidable_axes`), a single survivor (`single_survivor`) and `can_win`. A simulator failure is a **test failure, not a retry trigger**:
   `generate` imports `validate` but never `simulate`.
2. Regeneration is byte-identical across processes with different `PYTHONHASHSEED`.
3. Statistics over seeds 0..999 (computed in 2d-4):
   - **No selection on the culprit by construction.** Gating assigns depths so that no candidate on any axis is ever the unique extreme, and
     placement keeps facts per suspect within the validator's +-1 band. The smoke test asserts these conditions for **every attempt**, not only
     the final case, so `CULPRIT_UNIQUE_EXTREME` and `TRUTH_DEPTH_EXTREME` never fire and rejection never selects on them. (Checking only the
     final case would be vacuous: both codes are strict errors, so any accepted case lacks them.) Rejecting on them would also make a
     classifier "anyone but the unique extreme" beat chance: the review measured 0.32 against 0.25 on `short`.
   - **The culprit is never re-drawn:** `n[truth] == 0` in every accepted case, and the smoke test reports the retry rate per culprit role and
     per scene, so any bias from rejection sampling is visible.
   - Features that vary are tested with chi-square and Bonferroni correction (about 50 tests, one-sided where relevant): culprit position after
     the permutation (uniform); evidence-depth rank; text-length rank (defined in the 2d-4 spec as the rank of each suspect's total fact text
     length); and **culprit (role, motive) by goodness of fit**: for each cell the expected culprit count is the sum over cases of
     1[(role, motive) pair present] / S, tested on cells with expected count >= 5. (A two-sample test of culprit vs non-culprits is invalid:
     they are dependent within a case.)
   - Trivial classifiers ("pick the suspect with the max, the min, or anyone but the unique extreme of feature f", ties broken with a seeded
     stream) must score within chance + 3 sigma.
4. Pack-load smoke test: 200 seeds per (pack, supported preset): mean attempts <= 2, max <= 10, where an **attempt is one strict-validator call
   or one `skin_lint` call**, with the failure distribution per code. It lives in `tests/` behind the `slow` marker and as a `tools/` command;
   it cannot live in `packs` (a lower layer than `generate`).
5. `replay` and `explain` exist and are provably unreachable from a player surface (the player-surface architecture test is extended).

Decided with the user: the work is cut **horizontally by stage**; the pack changes are split into 2c.1a (before 2d-1) and 2c.1b (after the 2d-2
spec); the 2c.1a and 2d-1 specs are written **together**, since 2d-1 decides what 2c.1a must contain.

Out of scope: the LLM "dressing" pass (parent spec 4.9), the other three packs (2e), the MCP server (3), the agent loop (4), any frontend (5).

## 2. Architecture

A new layer `src/gumshoe/cases/generate/`. The layer rules already allow it to import core, model, rules, validate and packs; only
`generate/streams.py` is exempt from the no-randomness rule (which also bans `secrets`, `os`, `hash()` and file access). `generate` imports
the validator through `gumshoe.cases.validate.runner.validate`, never through the package-level `validate_case` alias (circular).

| Module | Responsibility |
|---|---|
| `streams.py` | `Stream(seed, spec_hash, stage_version, counter, stage_label)` seeded by `sha256`, with `child(label)` for per-entity sub-streams (parent 4.7); its own primitives, listed in 2.1 |
| `gen_context.py` | the frozen `GenContext`: pack, presets, the effective spec (`derive_spec`, refusing presets the pack cannot host), seed, preset, `spec_hash` (sha256 of the canonical JSON of the `Spec`), the version strings. Named `gen_context` to avoid confusion with `validate/context.py` |
| `roster.py`, `truth.py`, `timeline.py` | the structural stages (2d-1) |
| `facts.py`, `placement.py`, `gating.py` | the evidence stages (2d-2) |
| `assemble.py` | `build_case` (skeleton-only `Case` from stage outputs, 2d-2), then the final permutation and id assignment (2d-3) |
| `skin.py`, `skin_lint.py` | wording from the pack's templates, then the case-level text checks (2d-3, section 2.4) |
| `pipeline.py` | the fold over stages, the strict-validate step, the retry controller (2d-3) |
| `api.py` | `generate(...)`, `CaseGenerationError`, `GenerationTrace` (2d-3) |
| `tools/gen_dev.py` | `replay(seed, preset, pack, upto=stage, override={stage: output})` and a spoiler-marked `explain(case)`; `tools/` only, reusing `validate.routes` for closures and routes |

### 2.1 The stage contract and the streams

Every stage is a pure function `run(ctx, previous_outputs, stream) -> tuple[Output, tuple[Note, ...]]`. `ctx` is frozen. Each `Output` is a frozen
Pydantic model (the project's `Frozen`) built only from strings, ints, bools, `None`, tuples of these and nested `Frozen` models (no floats:
`canonical_json` forbids them), with a canonical digest. The digest gives golden snapshots (5 seeds per pack) and lets `replay` swap one stage's
output without touching the others. A stage never reads another stage's stream, never mutates its inputs and never logs; its `Note`s become the
`GenerationTrace`, attached to `CaseGenerationError` on failure.

Streams: CPython guarantees reproducibility only for `random()` and `seed()` (`shuffle`, `sample` and `randrange` changed across 3.10 to 3.12), so
`streams.py` implements its own primitives and the 2d-1 spec chooses between building them on `getrandbits` and a sha256 counter-mode generator
(the latter removes the dependency on CPython behaviour and the exemption). Required primitives: `below(n)` by rejection sampling (never modulo),
`shuffle`, `choice`, `sample`, and `rank(keys, label)` for the parent's rendezvous-hash pool sampling (4.8). Primitives accept only sequences and
raise `TypeError` for sets and frozensets (hash-based iteration order). They are pinned by golden values.

### 2.2 Truth symmetry and ids

Stages build in a canonical order. The truth stage **draws the culprit index, the method index and the motive reorder, and reorders the roster so
the culprit sits at index 0** (parent 4.11: the suspect-to-motive matching is drawn over the whole roster before the truth is chosen). Ids are never
a function of the canonical index and never include an evidence role: final ids are `make_id(prefix, seed, pool-key path)` where the path is
(entity kind, permuted neutral position, owner pack key), assigned in `assemble` after one random permutation of the neutral positions. (`Case`
sorts every entity list by id, so permuting list order alone would do nothing.) Ids are 8 hex characters; on a collision `assemble` re-salts
deterministically. A `DUPLICATE_ID`, `BAD_ID` or `DANGLING_REF` that survives is a bug and raises. "Neutral pool positions" (not "slots", which are
timeline time slots) name entities inside the stages.

### 2.3 Retry (precise)

Stage order: `roster < truth < timeline < facts < placement < gating < assemble < skin`, preceded by the effective-spec step, which has no stream.
(`FixStage` lists `skin` before `assemble`; the controller uses the pipeline order.)

State, per stage `s` in that order: a **stream counter** `n[s]` and a **retry count** `k[s]` (not stored). `Case.stage_attempts` is the fixed-order
tuple `(n[roster], ..., n[skin])`, length 8; the order is a constant in code and a test asserts the length. `Case.attempt` is the number of
attempts used. An **attempt** is one strict-validator call or one `skin_lint` call; the budget is 20.

On a failed attempt:
1. If any issue's `fix_stage` is `pack`, `none` or `assemble` (decided by `fix_stage`, **never by the code's name**: `PACK_SOURCE_KIND_CAPACITY`
   is a retryable `placement` code), raise `CaseGenerationError`.
2. Otherwise let `s` be the earliest `fix_stage` of the issues, in pipeline order. Do `k[s] += 1`.
3. While `k[s] > 5`: set `k[s] = 0` and move `s` to the previous stage; if there is none (`s` was `roster`), raise
   `CaseGenerationError("escalation exhausted")`; otherwise `k[s] += 1`.
4. For every stage `t >= s` do `n[t] += 1`, and for every `t > s` set `k[t] = 0`. Re-run from `s`.

Stream keys use `n[stage]`, **never `Case.attempt`**. With a budget of 20 the escalation is effectively one level deep (the review's experiment: a
roster-caused failure coded as `facts` costs at least 16 attempts); so failures caused by an earlier stage must be **prevented by the feasibility
contract of section 3, not retried**.

Replay is exact: each stage runs once with its stored final counter on the previous stages' final outputs. Validation runs on the **assembled,
skinned** case, and a test asserts `validate(skeleton)` and `validate(skinned)` report the same codes. The validator hides later groups after an
error in an earlier one (group 1 or 3 hides 2-11 or the later groups; a group 4 error hides 6, 8 and 9; a group 6 error hides 8), so the controller
sees a prefix of the problems and a placement error can mask a facts error, costing up to 5 attempts; this cost is expected and measured.

Versions: per-stage versions are constants in code; `Case.skeleton_algo_version` is an int bumped whenever any stage version changes (the parent's
rule: the shared code includes it); `Case.generator_version` is the canonical string `"roster=1,truth=1,timeline=1,..."`. Incompatible versions are
refused with a clear message. Repair hints go into the `GenerationTrace`; targeted repair is a later optimisation.

### 2.4 Skeleton versus skin

The skeleton is everything the validator and simulator judge; skin (display names, descriptions, fact text, contradiction text, `intro`,
`smalltalk_allow`, persona fields) is wording and owns no validator code. **Verified by experiment (twice):** the hand-built strict case with every
skin field blanked validates with 0 issues and gives the same simulator verdict. So `build_case` produces a skeleton-only case, which is how 2d-2
gets real validator feedback before skin exists.

But the parent spec also requires case-level *text* checks the validator does not implement: the per-case leak lint (4.5), label versus display name
(4.6), identical-sentence dedupe (4.2) and claim fidelity, including for the accused of a framing lie (4.9). They are owned by `skin_lint.py`
(2d-3); a failure retries the `skin` stage with a new stream. A `skin_lint` call counts as an attempt.

### 2.5 Who produces what

Every field of `Case` has exactly one owner stage. Detailed shapes are fixed in the sub-specs.

| Field | Owner |
|---|---|
| `spec`, `scene_type` | effective spec / roster |
| `theme`, `pack_ref`, `pack_versions` | `api` (from the pack) |
| `id`, `seed`, `attempt`, `stage_attempts`, `generator_version`, `skeleton_algo_version`, `schema_version`, `origin` | `api` / pipeline |
| suspects: neutral position, label, aliases, role, motive (the roster output is its own type: a `Suspect` needs `secret_fact`) | roster |
| methods, motives, locations (kind, aliases, `decorative`) | roster |
| the **record kinds** used by the case, and each suspect's **secret record kind** | roster |
| `truth` | truth |
| `timeline` (events, crime event, **each suspect's place in every slot**, who has opportunity) | timeline |
| facts: kind, claim, effects, `truthful`, `speaker`, `exposed_by`, `topic`, `timeline_ref`, `trace_kind`, `Suspect.secret_fact` | facts |
| `Fact.source` (kind and target), `record_sources` (the (kind, subject) pairs), `Suspect.knows`, `Fact.exposure_hook` | placement (facts declares the intended shape; placement assigns the source) |
| `requires` on suspects, locations, record sources and facts; `start` | gating |
| final ids and the order of every list | assemble |
| display names, descriptions, `Fact.text`, `Fact.contradiction`, `intro`, `smalltalk_allow`, `Suspect.traits/style/secret_text`, `skin_rev`, `skin_hash` | skin |

Location aliases: **empty in v1** (a ruling: the castle has one name per kind and no alias forms; revisit if Jev mismaps a place name).

## 3. Cross-stage contracts

2d-1 fixes decisions that 2d-2 must live with, so its spec states them as invariants of the stage outputs and tests them. The second review
checked them against the validator and the castle.

(a) **Record kinds vs roles.** For every role in the roster, at least one of the case's record kinds is allowed for that role and is about a suspect.
Short and standard use exactly 2 record kinds (`COUNT_MISMATCH` counts the distinct kinds in `record_sources`); a record-kind set drawn
independently of the roster works only about half the time (castle: short 106 of 210 role pairs, standard 77 of 168), so kinds are drawn
**conditionally on the roster**. Long always uses all 3.
(b) **Symmetric exposer place.** The culprit's own record exposes the lie by showing where they really were (the scene), and the culprit is drawn
uniformly, so **every suspect's secret record kind must attest the scene's location kind and that suspect's crime-slot place**; otherwise the truth
would have to be drawn from a subset, which is a structural tell. 2c.1a adds a pack check: a preset needs enough **hosting scenes** (a scene allowing
enough methods and having enough eligible roles, where a role is eligible when a record kind of its usable for the scene); the roster picks among
hosting scenes and draws roles from the eligible ones (it is drawn before the truth). The 2c.1a/2d-1 spec refines this: only hosting scenes matter.
(c) **Scene source capacity.** The scene's single search source holds at most 4 facts, but the how-axis alone wants one `proves` plus M-1 absent
traces, plus the who-proof. Castle numbers: scene demand 4/4 (short, no room), 5/4 (standard), 6/4 (long). The overflow must live on non-scene
locations inside each trace's `location_kinds`, and every trace kind must be in `scene.allowed_trace_kinds`.
(d) **Opportunity count and the depth bands** (and `r`, added by the 2d-2 spec together with its consumer) are `PresetDef` fields copied into `Spec` by `derive_spec` (g11's `SPEC_MISMATCH` demands
`derive_spec(preset, pack) == case.spec`). 2d-1 therefore adds `opportunity` to `PresetDef`, `Spec`, `derive_spec` and the field-role map, with fixtures and goldens (`supports` follows in 2d-2). **Per-seed draws within those bands live in stage outputs, never in `Spec`.**
(e) **The who-proof shape** is an open point of the 2d-2 spec (presence at the scene cannot prove guilt when wrong suspects also have opportunity).
Since a truthful witness claim requires co-location (parent 3), the 2d-1 timeline output records each suspect's place in every slot, so later
co-location needs are satisfiable without redrawing the timeline.
(f) **Every chosen record kind is used.** The K chosen kinds must each be the kind of at least one record source holding at least one fact
(`COUNT_MISMATCH(record_kinds)` has `fix_stage` roster but placement causes it). The structural probe builds one stub source per kind.
(g) **Validator results depend on ids.** Route tie-breaks use sorted fact ids, so `DEPTH_RANGE` and `ACTIONS_RANGE` can flip when `assemble`
reassigns ids. 2d-2 rule: gating makes **every minimum-size solution** satisfy the windows, tested by validating the same skeleton under 3 id
permutations and expecting identical codes.

**Structural probe (end of 2d-1).** A partial case with one stub secret fact per suspect and one stub record source per chosen kind runs groups 1,
2, 3, 4, 5, 7, 10 and 11 of the validator (groups 6, 8 and 9 are skipped); the 2d-1 test asserts no issue has a `fix_stage` in
{roster, truth, timeline}. The remaining issues (UNTOUCHABLE_CANDIDATE, NO_STATEMENT, EMPTY_LOCATION, ORPHAN_ENTITY,
OPPORTUNITY_NOT_RULED_OUT) belong to later stages.

## 4. Decomposition

Each plan has its own spec and plan, written after the previous plan is built (a "re-plan checkpoint"), except that the 2c.1a and 2d-1 specs are
written together.

| Plan | Delivers | Ends with |
|---|---|---|
| **2c.1a** pack inputs for structure | Per-record-kind `location_kinds` for every record kind; record display names (an `Entry` per record kind) and a `{record}` placeholder so truthful and lying record facts draw names from one pool; role display nouns and spoken forms with label hygiene on suspect labels and aliases at pack load; the symmetric-attestation pack check of (b); `Pack.skeleton_view` and its domain tag extended; castle content in reviewed chunks as in 2c | A castle that supports roster and timeline |
| **2d-1** structure | `streams.py`, `GenContext`, roster (suspects from roles with **distinct roles per roster**, methods, motives with V = S and the Hall-checked matching draw, locations, scene, record kinds), truth, timeline; the `PresetDef`/`Spec` changes of (d); `replay` | Stage outputs with golden digests, the contracts (a)-(f) as invariants, and the structural probe |
| *(spec of 2d-2 is written here, against 2d-1)* | | |
| **2c.1b** pack inputs for evidence | Per-method `absent` and per-motive `ruleout` templates (claim slots fixed by the 2d-2 spec); a who-proof family and a physical who-rule-out family; a victim and `intro` family; the `smalltalk_allow` vocabulary; a contradiction family; per-role persona style; castle content in reviewed chunks | A castle that supports facts and skin |
| **2d-2** evidence | Facts (one lie plus exposer per suspect, the symmetric evidence, records), placement (greedy with swap repair, at most 4 facts per source), gating (layered depths, disjoint solution routes, (g)), and the skeleton-only `build_case` | Skeleton cases that pass `validate(case, pack, STRICT)` |
| **2d-3** assembly | The permutation and ids, skin, `skin_lint`, the retry controller, public `generate()`, `CaseGenerationError`, `GenerationTrace`, the smoke test, a worked retry-trace table in its spec (attempt, failing code, stage, `n[]`, `k[]`) | `generate(seed, preset, castle)` returns valid, byte-identical cases |
| **2d-4** quality | The statistics of criterion 3, simulator agreement, `explain`, difficulty tuning within the `PresetDef` bands, the `slow` marker, any families added by the corpus-test items; then **pin the castle skeleton digest** | Success criteria 3 to 5 met; no seed is published before the pin |

The digest is pinned at the **end of 2d-4**, because 2d-4 may add families (hand-off items 7 and 8, families are in the skeleton hash) and tunes
the bands that change every seed's output.

## 5. Mapping of the 2c hand-off list (2c spec section 11)

| Item | Resolved in |
|---|---|
| 1. Per-method absent and per-motive rule-out templates | 2c.1b |
| 2. Record names from one pool for truths and lies | 2c.1a (`{record}`) |
| 3. Which location kinds a record kind may be about | 2c.1a (every record kind) |
| 4. The accused in a framing lie (claim fidelity on the accused) | 2d-3 (`skin_lint`; the facts stage makes `{who}` the accused) |
| 5. Grammar of "they" | deferred: no pack uses it |
| 6. Distinct roles per roster | 2d-1 (roster) |
| 7. Proof and rule-out vocabulary carrying polarity | 2d-4 (corpus test decides) |
| 8. Witness manner phrases | 2d-4 (corpus test decides) |
| 9. Lint limits | as needed; none blocks 2d |
| Pin the castle skeleton digest before any seed is published | end of 2d-4 |

## 6. Testing strategy

- **Per stage:** invariant tests against the stage output (not by reusing validator rule functions) and golden digests for 5 seeds per pack.
- **Streams:** property tests (same key gives the same sequence; different labels are independent; the global `random` is never touched);
  golden values pin the primitives; sets and frozensets are rejected.
- **Determinism end to end:** regeneration compared across two processes with different `PYTHONHASHSEED`.
- **Retry:** deliberately bad stage outputs fed to the controller, asserting the restart stage follows the pipeline order, that
  `pack`/`none`/`assemble` codes raise at once (by `fix_stage`), that escalation past `roster` raises, that `k` and `n` behave as in 2.3, and
  that replay with the stored counters reproduces the case exactly. The reviewer's throwaway controller model is a good property-test oracle.
- **Speed:** the default suite stays fast. The 1,000-seed statistics and simulator agreement run behind a `slow` marker (added to
  `pyproject.toml`). Instead of a wall-clock assertion, assert a **validator-call budget** per `generate` and report timing.
- **Provable tests:** every new invariant test is shown able to fail on broken data, as in the castle tests.

## 7. Risks, open points, and which spec wins

- **`short` is marginal on the castle (a top risk for the 2d-2 spec).** Guaranteed sources give a cap of floor(3.2 x sources) per source kind. For
  `short` (S=4, M=3): search demand is the 4 who-decisive facts plus 2M = 6 how facts = 10, against a cap of 9; the how facts belong to no
  suspect (which keeps facts-per-suspect equal) and M=3 is not a multiple of S=4, so moving them into suspect-owned sources breaks equal ownership
  and creates a unique minimum. Options for the 2d-2 spec: put the who-decisive facts in the suspect records (exactly full: 12 of 12), allow a
  `gate_log` record (only 34% of short kind-pairs), or interrogation facts without a speaker. Standard and long are fine except the scene
  overflow of (c). `SHAPE_MISMATCH` is a further coupling: on each axis every candidate's decisive facts, and its supports, must come from one
  source kind, so all who rule-outs and the who-proof share one source kind. If `short` proves infeasible the fallback is a pack or preset
  change, decided in the 2d-2 spec.
- **Retry rates.** Facts owns 32 of the 81 codes. If the smoke test shows a mean above 2 attempts the answer is targeted repair using the trace's
  hints, never loosening a rule.
- **Selection bias** from rejection sampling: prevented by construction and measured (criterion 3).
- **The evidence design is the hardest part** and will likely need rework once the first cases run, which is why its spec is written only after
  2d-1 exists.
- **Pack inputs still missing for later plans** (ranked): a who-proof family; a physical who-rule-out family; role display nouns and spoken
  forms (2c.1a); record display names (2c.1a); record `location_kinds` (2c.1a); absent and rule-out templates (2c.1b); a victim and `intro`
  family; a `smalltalk_allow` vocabulary; a contradiction family; per-role persona style.
- **Open for the sub-specs:** the exact shape of each stage output; how depth targets and `r` are drawn within their bands; the placement
  swap-repair details; the shape of `explain`; the streams construction (`getrandbits` or sha256 counter mode).
- **Cost of the stage split:** a defect in an early stage's output shape can force changes in several later plans; golden digests make such a
  change visible but not free.
- **Which spec wins.** The overview wins on: the retry budget unit (validator calls, not "whole-case restarts"), equal-by-construction
  fairness, and returning hints in a trace instead of logging. The parent wins on `skeleton_algo_version` (kept, section 2.3) and on rendezvous
  sampling (kept as a primitive). On depth independence versus rejection neither wins as written: criterion 3 above replaces both.
