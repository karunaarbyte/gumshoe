# The generator's assembly, retry controller and public API (2d-3a): design

Status: design, written 2026-10-05 after a prototype that was run against the real validator and simulator (every number below was measured
on it), then reviewed twice by independent adversarial reviewers (findings and what became of them: section 12; the second review checked the fixes of the first).
Extends `2026-10-03-generator-2d-overview-design.md` (sections 2.2 to 2.5: ids, retry, skeleton versus skin, ownership) and builds on
`2026-10-05-generator-evidence-2d2-design.md` (the evidence stages and `build_case`, including its section 12). Parent:
`2026-10-01-case-engine-design.md` (sections 3 and 4). Where this document and the overview disagree, section 9 says what changed and why.

## 1. Intent and the split of 2d-3

The overview's 2d-3 bundles three things of very different kinds: assembly and retry (code that needs no new content), skin and `skin_lint`
(needs wording the castle does not have), and the public `generate()` that ties them together. This spec covers the first and the third
and defers the second:

| Plan | Delivers | State |
|---|---|---|
| **2d-3a** (this spec) | final ids, the pipeline and its retry controller, `generate()` and its errors, `regenerate`, the smoke test, replay with stage counters, a `generate` and a `smoke` command | designed and prototyped here |
| **2c.1b** | the castle wording the evidence needs (section 10 lists exactly what) | to be written, in reviewed chunks with the user |
| **2d-3b** | the template skin, `skin_lint`, the victim and `intro`, replacing the identity skin stage | spec written after 2c.1b, against what it produced |

The split follows the overview (it already sequences 2c.1b before skin) and the process rule that each plan gets a spec written against what
the previous one actually produced. Skin cannot be designed before the pack content it renders exists, and the retry controller, the ids
and the public function do not depend on it, so they come first. **Until 2d-3b the skin stage is the identity**: `generate()` returns a
valid, solvable, skeleton-only case whose text fields are blank (it loads in `play`, but there is nothing to read). That is stated in the
case itself: `skin_rev` is 0.

Success criteria:
1. `generate(seed, preset, castle)` returns a case for every seed 0..999 and every claimed preset (short, standard, long) in **one attempt**
   (one strict-validator call, zero issues), and the simulator agrees (`judge`: every axis decidable, a single survivor, `can_win`).
2. The retry controller follows the overview's rules exactly, shown against an independent model of them on random failure sequences, and
   against the real validator on real faults.
3. Output is byte-identical across processes with different `PYTHONHASHSEED`; golden digests pin the final case for 5 seeds per preset.
4. `regenerate(case, pack)` rebuilds a stored case from its seed and stage counters with one pass of every stage and one validator call,
   however many attempts the original took, refuses a case made by other code, and raises (never draws another case) if that one pass does
   not validate.
5. No id of a final case says which suspect is the culprit, which method is true, what kind a fact is, or how a stage drew it, and the same
   seed has other ids in another preset or pack.

Out of scope: skin, `skin_lint`, the victim and `intro` (2d-3b); statistics at 1,000 seeds beyond the smoke counts, `explain`, difficulty
tuning, the `slow` marker, and pinning the castle skeleton digest (2d-4); pack content (2c.1b) and pack-check hardening (2d-2 spec, section 10).

## 2. What the prototype established

- **The design is valid by construction on every seed measured.** 3,000 skeleton cases (seeds 0..999 times the three presets, the depth the
  facts stage draws) validate with zero issues and no skipped group; no stage raised `GenerationError` on any of them (85 s). Through the
  public path, `python -m gumshoe.cases smoke --seeds 1000` gives, per preset, 1,000 cases, **mean 1.00 attempts, max 1, 0 failures**
  (short 16 s, standard 24 s, long 48 s). The 2d-2c review had already run seeds 200..599 at every feasible depth (2,400 cases, clean).
- **The permutation of the overview (2.2) changes nothing anyone can observe, so it is dropped** (section 4). Measured on 400 `short` seeds
  with and without it: the culprit's id rank was 99/100/100/101 against 95/96/98/111 (both uniform), and the share of cases in which the
  suspects' motives come in the suspects' own order was 21 against 13 of an expected 16.7 (both at chance).
- **Contract (g) holds for the final case.** Renaming every entity (suspects, methods, motives, locations, events, facts) changes neither the
  validator's verdict nor the best solution's size, depth and actions, at every feasible depth (seeds 0..39 per preset in the test).
- **Real faults work as the design says**: a facts output with `x_s0` only supporting is rejected (`NO_POSITIVE_EVIDENCE`, `SHAPE_MISMATCH`)
  and redrawn from `facts`; a gating that opens everything is rejected with `ACTIONS_RANGE` (placement) and `DEPTH_RANGE` (gating) and
  the **earliest** of those stages, `placement`, is restarted.
- **More seeds.** The independent review ran seeds 1000..3999 for every preset (9,000 more cases): no `GenerationError`, one attempt each.
- **Cost.** Stages, assembly and one strict validation cost about 16 ms (`short`), 24 ms (`standard`) and 48 ms (`long`) per case, the validator being most of it.

## 3. The pipeline

Pipeline order, the retry order and the order of `Case.stage_attempts` (length 8):

`roster < truth < timeline < facts < placement < gating < assemble < skin`.

`gen_context` gains `PIPELINE = (*STAGES, "assemble", "skin")`; `STAGES` stays the six structural stages that `structure.py` folds, and
`STAGE_VERSIONS` gains `assemble: 1` and `skin: 1` (1 means the identity skin; 2d-3b brings 2). `generator_version()` is the stage versions in
`PIPELINE` order: `"roster=2,truth=1,timeline=1,facts=1,placement=1,gating=1,assemble=1,skin=1"`. `check_counters(counters)` is the one
validation of a mapping of stage counters (a known stage, a non-negative int that is not a bool), used by the fold and the controller.

`structure.py` gains `run_stage(ctx, stage, out, counter=0)`, one structural stage on the outputs before it with its stream counter, and
`run_structure(..., counters=None)` passes `counters.get(stage, 0)` to it. The fold used by `replay` is therefore the same code the controller
runs.

`pipeline.py` holds the retry state (`Retry`) and the run (`run_pipeline`). A run keeps the outputs of the stages before the restart stage
and re-runs the others, so a restart from `facts` costs three stages, not eight. `run_pipeline` takes keyword arguments `counters` (start
the stages at stored counters: a replay), `budget`, and three injection points, `runner` (the structural stages), `validator` and `skin`,
so tests can feed it faults; their defaults are the real ones, the validator being the strict one **with the context's presets** (a custom
preset table reaches the validator too: without it the spec rule `SPEC_MISMATCH` rejects every case).

## 4. Final ids (the assemble stage)

`assemble(ctx, truth, timeline, facts, placement, gating)` is `build_case` (2d-2) followed by `rename(case, id_map(case))`. It draws nothing.

- **Ids.** `make_id(prefix, case.id, kind, index, salt)`: `case.id` is the neutral skeleton case's id, itself a hash of the seed, the preset, the
  pack id, the pack's skeleton hash and the spec; `kind` is one of suspect, method, motive, location, event, fact; `index` is the entity's place
  among the **sorted neutral ids of its kind**; `salt` starts at 0 and goes up on a collision with any earlier id (any kind), which is
  deterministic and in practice never happens (8 hex digits, about 120 ids). Prefixes are `s m v l e f`, and **every kind of fact shares
  `f`**, so an id says nothing about what a fact is (neutral fact ids such as `sec_s0`, `x_s0` and `n_gate_log` are exactly what must not
  survive). A stage output that refers to nothing (a gate on a fact that does not exist) makes `assemble` raise `GenerationError` (a
  `KeyError` or a pydantic `ValidationError` from the rename is converted), which the controller treats as a failed attempt (section 5).
- **Why the code of the case is in the hash.** The culprit is always neutral index 0 of the suspects, so if the hash held only the seed, the
  culprit's id (and the true method's and motive's) would be the same in every preset and every pack for a given seed: a player who solved
  seed N in one preset would see the answer's id again in another (found by the independent review, measured on seeds 0..19: 20 of 20
  identical across the three presets). Hashing `case.id` makes ids a function of (seed, preset, pack, spec), and the final case id of
  section 6 also holds the generator version.
- **Why no permutation (amendment to overview 2.2 and parent section 3).** The overview has the assemble stage draw one random permutation
  of the neutral positions per kind and hash the permuted position. But the id is already a hash, so the order of the final ids (the only
  order a player sees, because the case lists every entity sorted by id) is pseudo-random whether or not the positions were shuffled first;
  the prototype measured this (section 2), and the independent review repeated it on 2,000 seeds (rank of the culprit, the true method and
  the true motive uniform with and without a shuffle; the suspects' motives in the suspects' own order at chance in both). A permutation that no
  test can ever see fail breaks this project's rule that every invariant is shown able to fail, so it is dropped, and `assemble` has no
  stream (its counter `n[assemble]` stays in the 8-tuple, unused). The properties that matter are tested directly, each against a break that
  fails it (section 8): ids that ignore the case id (the culprit's rank never changes, and the same seed repeats its ids across presets); ids
  that ignore the kind (the suspects' motives follow the suspects' own order in every case).
- **`rename`** replaces every id field by field (suspects: id, motive, secret fact, requires, knows; locations: id, requires; record-source
  subjects and requires; methods and motives; events: id, actor, place; facts: id, requires, exposed_by, timeline_ref, speaker, effect
  candidates, claim actor and place, source and exposure hook; truth; start). It works on the dumped form and `Case.model_validate`, so every
  list comes out sorted by its new ids. A record `SourceRef`'s `target` is a record kind, not an id, and is kept. A test renames back with the
  inverse map and expects the neutral case, and another scans the dumped JSON for every neutral id as a quoted string.
- **Contract (g).** The validator runs on the final case, so id-dependent tie-breaks are judged on the ids a player gets; the 2d-2c
  design makes every minimum-size solution fit the windows, and a test checks the verdict and the solution's shape against the neutral case.

## 5. The retry controller

Rules (overview 2.3, restated; `Retry` implements them, `tests/generate/retry_model.py` states them again from their definitions):

- State: a stream counter `n[s]` and a retry count `k[s]` per stage. An **attempt** is one pass over the stages that ends in a strict-validator
  call or in a stage raising `GenerationError`; the budget is 20 attempts. `Case.attempt` is the number of attempts.
- On a failed attempt, only issues of **error** severity count (every strict code is an error today; the filter keeps imported-profile
  warnings from ever causing a retry or a stop, even a warning whose code no stage can fix).
  1. If any error's `fix_stage` is `pack`, `none` or `assemble`: stop (`CaseGenerationError`; a bug or a bad pack, decided by `fix_stage`,
     never by the code's name).
  2. Otherwise `s` is the earliest `fix_stage` of the errors in pipeline order; `k[s] += 1`.
  3. While `k[s] > 5`: `s` becomes the previous stage with `k[s] += 1`; past `roster` the run stops (`Exhausted`).
  4. Every stage from `s` on gets `n += 1`; every stage after `s` gets `k = 0` (which also resets the stage the walk-back left). Re-run from `s`.
- `n[s]` keys the stage's stream (`ctx.stream(stage, n[stage])`), never the attempt number; `Case.stage_attempts` is `(n[roster], ...,
  n[skin])`.
- **A stage that raises `GenerationError` is a failed attempt with that stage as its fix stage** (code `STAGE_ERROR`, the message in the attempt's
  `detail`), restarted by the same rules: a new stream is a new draw, and the walk-back reaches the stage that made an output this stage
  cannot use. This amends the first draft of this spec, which stopped the run: the independent review showed a pack that passes today's pack
  checks (the castle with one location kind removed) on which the roster stage raised on 9 of 30 `short` seeds, which a restart cures. On the
  castle itself it never happens (none in 12,000 cases); `smoke` shows it as retries if it ever does. The assemble stage is one such stage: a
  gating output with a dangling gate fails at `assemble` five times and then walks back to `gating` (tested). Those five attempts are wasted
  (the assemble stage draws nothing, so retrying it cannot change its output) and the cost is accepted: a rule that sent an assemble failure
  straight to the stage that feeds it would be one more special case for an event that does not happen. A stage error with an empty message is
  recorded with the exception's class name as its detail.
- **The skin stage in 2d-3a** is `identity_skin`; a failure with `fix_stage` skin cannot occur (the catalogue has no skin-coded validator
  code; `skin_lint` of 2d-3b owns them), and a restart from `skin` would only re-run the identity until the budget ended.

**Trace.** `GenerationTrace(attempts)`, each `Attempt(number, first_stage, counters, codes, restart, detail="")`: the attempt, the stage the run
(re)started from, the counters used (in `PIPELINE` order), the error codes (or `STAGE_ERROR`), the stage restarted next (None when the run
ends) and a stage's own message. `CaseGenerationError(message, trace, report)` carries the same trace and the last validator report (None
when the last attempt was a stage error). Messages: "no stage can fix <codes>", "the budget of <n> attempt(s) ran out" (the budget must be at least 1), "every stage used up its
retries", the last two followed by "(the last failure: the <stage> stage failed: ...)" when the last attempt was a stage error.

**Worked example** (real output of `run_pipeline` with a scripted validator that fails seven times with a facts code and then twice with a
gating code, pinned line by line in `test_the_worked_retry_trace_with_an_escalation`; the fifth failure is the last facts retry, the sixth
escalates):

```
 1 from roster    n=[0, 0, 0, 0, 0, 0, 0, 0] NO_POSITIVE_EVIDENCE -> restart facts
 2 from facts     n=[0, 0, 0, 1, 1, 1, 1, 1] NO_POSITIVE_EVIDENCE -> restart facts
 3 from facts     n=[0, 0, 0, 2, 2, 2, 2, 2] NO_POSITIVE_EVIDENCE -> restart facts
 4 from facts     n=[0, 0, 0, 3, 3, 3, 3, 3] NO_POSITIVE_EVIDENCE -> restart facts
 5 from facts     n=[0, 0, 0, 4, 4, 4, 4, 4] NO_POSITIVE_EVIDENCE -> restart facts
 6 from facts     n=[0, 0, 0, 5, 5, 5, 5, 5] NO_POSITIVE_EVIDENCE -> restart timeline
 7 from timeline  n=[0, 0, 1, 6, 6, 6, 6, 6] NO_POSITIVE_EVIDENCE -> restart facts
 8 from facts     n=[0, 0, 1, 7, 7, 7, 7, 7] DEPTH_RANGE -> restart gating
 9 from gating    n=[0, 0, 1, 7, 7, 8, 8, 8] DEPTH_RANGE -> restart gating
10 from gating    n=[0, 0, 1, 7, 7, 9, 9, 9] ok
```

(Attempt 6 is the sixth failure at `facts`: `k[facts]` would be 6, so `timeline` is restarted instead, with `k[timeline]` = 1 and `k[facts]`
= 0; at attempt 7 `facts` starts again from a clean `k`.) The 10th attempt returns a case with `attempt = 10` and `stage_attempts = (0, 0, 1,
7, 7, 9, 9, 9)`.

## 6. The public API

`generate/api.py`:
- `generate(seed, preset, pack, presets=PRESETS) -> Case`, `generate_traced(...) -> (Case, GenerationTrace)`. A preset the pack cannot host
  raises `UnsupportedPreset` (a user error, from `GenContext.of`); no valid case raises `CaseGenerationError`. The pack must have passed the
  pack checks (`load_pack`, `load_builtin_pack`); the generator does not re-check it, and a pack that fails them can raise anything.
- `regenerate(case, pack, presets=PRESETS) -> Case`: reads the stored seed, preset and `stage_attempts`, runs each stage once and the
  validator once (a budget of one attempt). It raises `VersionMismatch` (a `ValueError`) when the case has no seed or pack reference, another
  `skeleton_algo_version` or `generator_version`, another pack skeleton hash, **another spec** (a preset table that gives the stored case another
  `Spec`), or a counter tuple of the wrong length: "incompatible versions are
  refused with a clear message" (overview 2.3). If that one pass does not validate (the validator changed since the case was made) it raises
  `CaseGenerationError`: it never retries into a different case. The result equals the original except `attempt` (1).
- **Export.** `gumshoe.cases` exports `generate_case` (this `generate`) and `CaseGenerationError`. The name is not `generate`: that would
  replace the subpackage `gumshoe.cases.generate` as an attribute of the package, so `import gumshoe.cases.generate.pipeline as p` and a
  `monkeypatch.setattr("gumshoe.cases.generate.pipeline.X", ...)` would fail (found by the review; a test keeps the modules importable by
  path). `import gumshoe.cases` now loads the generator (the architecture test is static, so "the play layer cannot reach `generate`" holds for
  explicit imports, as the layer test checks); a lazy export is possible later if the load time matters. `generate_case` returns the truth, so
  a server calls it, never a player view.

**Bookkeeping stamped on the case** (meta fields; no rule reads them): `id = make_id("c", seed, preset, pack.id, pack skeleton hash, spec hash,
SKELETON_ALGO_VERSION, generator_version)` (a shared code names one case, and a later stage version, such as the skin of 2d-3b, names
another), `seed`, `generator_version`, `skeleton_algo_version`, `pack_versions = (("skeleton_rev", r),)` (2d-3b adds `skin_rev` when there is a
skin), `attempt`, `stage_attempts`, `theme = pack.id`, `skin_rev = 0` (no skin yet), `skin_hash` (of the skin fields: blank). The id holds the pack's **skeleton** hash only, so a pack that differs only in wording (`skin_rev`) gives
the same id; with no skin that is the same case, but 2d-3b must decide whether `skin_rev` (or the skin hash) joins the id, because two cases
with different text must not share one.
**`SKELETON_ALGO_VERSION` stays 2**: adding the assemble and skin stages changes no existing stage version, and nothing is published before
the 2d-4 digest pin; 2d-3b and 2d-4 decide whether to bump it when they change stage output.

## 7. Developer tools

- `gen_dev.replay(..., counters=None)`: stage counters for the fold (`{stage: n}`; a retried case's `stage_attempts` zipped with `PIPELINE`),
  checked by `check_counters` like the controller's (an unknown stage or a negative counter is a `ValueError`).
- `gen_dev.smoke(pack, preset, seeds) -> SmokeReport`: attempts per case, the failed-attempt codes (stage errors included), and the seeds that
  gave no case; a seed that gives no case is reported, not raised, and a run that made no case says so ("no case was made"). `SmokeReport.ok` is the overview's pack-load smoke criterion: **at least
  one case, no failed seed, mean attempts at most 2, max at most 10** (a run over no seeds is not a pass).
- CLI: `python -m gumshoe.cases generate SEED [--preset P] [--pack NAME] [-o FILE]` (the case JSON on stdout or in a file; it names the
  truth, like `simulate`) and `python -m gumshoe.cases smoke [--preset P] [--pack NAME] [--seeds N]` (exit 1 when the criterion fails).

## 8. Testing strategy

- **Retry model.** `retry_model.py` restates the rules from their definitions (k is "restarts of this stage since a stage before it was
  last restarted", n is "restarts at this stage or an earlier one"), not as a copy of `Retry.fail`; 40 random failure sequences over one to
  three stages each (so that a stage fails again and again) compare restart stages, exhaustion, `n` and `k`, and a test checks that those
  sequences really do escalate (at least 10) and exhaust (at least 3); the comparison is shown to reject a controller that never escalates;
  direct tests pin the first failure, the sixth (escalation), a walk-back past a used-up stage, and roster exhaustion.
- **Pipeline.** With a scripted validator and a recording runner: which stages re-run (and with which counters) for a facts failure and for
  mixed codes, that warnings never retry or stop (also an unfixable one next to a retryable error), that a retried case is exactly what its
  stored counters replay (scripted, and after a real fault), the two worked traces pinned line by line, the model against a pile-up of
  failures, the skin stream key, the 20th attempt (may succeed, a 21st is never made), a custom preset table, and each stop (an unfixable
  code scripted and one real `DANGLING_REF` from a bad skin; the budget; exhaustion; a stage that always raises). Stage errors: one that
  raises once is redrawn, and a dangling gate walks back from `assemble` to `gating`. Two real faults, caught by the real validator: facts
  and gating, above.
- **Final ids.** No neutral id survives anywhere in the dumped case; every id matches `[smvlef]_[0-9a-f]{8}` and every fact starts `f_`;
  renaming back gives the neutral case (a location gate included); a collision (a stubbed hash that collides) raises the salt; a stage output
  that refers to nothing is a `GenerationError`; the verdict and the solution's shape equal the neutral case's at every feasible depth; the same
  seed has no truth id in common across the three presets and another pack; **no ordering of the ids points at the truth**: chi-square over
  500 seeds per preset for the truth's rank among suspects, methods and motives, and the share of cases in which the suspects' motives come in
  the suspects' own order stays within chance (`1/S!`) plus three sigma.
- **Every seed.** 200 seeds per preset through `generate_traced`: one attempt, no codes, counters zero.
- **Determinism.** The golden snapshot (5 seeds per preset) gains the **final** case's `skeleton_digest` next to the six stage digests and the
  neutral case digest; the existing cross-process test (which reuses `stage_digests`) covers it.
- **Tools.** The smoke report's arithmetic and criterion (a faked `generate_traced`), replay with a counter and its refusals, both commands
  (files, stdout, refusals, exit codes).
- **Public face.** `generate_case` and `CaseGenerationError` are exported and the generator's modules stay importable by path.
- **Every new test shown able to fail** (the plan's "Prove it can fail" steps; the results are in the plan).

## 9. Amendments to the overview

- **2.2 (ids): no permutation, and the case's code in the hash** (section 4). The overview's other id rules stand: ids are `make_id(prefix, ...)`,
  8 hex digits, never a function of an evidence role, re-salted deterministically on a collision, and a `DUPLICATE_ID`, `BAD_ID` or
  `DANGLING_REF` that survives is a bug and stops the run (rule 1). The path no longer includes "owner pack key": nothing needs it.
- **2.3 (retry)**: an attempt is a validator call or a stage's `GenerationError`; a stage error is retried by the same rules, with that stage as
  its fix stage (section 5); only error-severity issues count; the budget of 20 counts attempts.
- **2.5 (ownership)**: `Suspect.knows` is derived by `build_case` (2d-2c, section 12); `Case.skin_rev` is 0 until 2d-3b; the assemble stage
  owns the final ids and nothing else.
- **2.1 (stage contract)**: the stages return an `Output` and no `Note`s (since 2d-1); the `GenerationTrace` records attempts, which is what
  the overview's retry table needs.

## 10. What 2d-3b and 2c.1b need (the survey)

Checked against the castle (`castle.toml`: 12 template families, per-method trace templates, per-motive `secrets`, location descriptions,
role traits and nouns) and the evidence the facts stage builds. A fact's text comes from a family chosen by its **fact kind and source kind**.

| Fact | Kind, source | The castle has | Missing (for 2c.1b) |
|---|---|---|---|
| `sec_k` | SECRET, record | the motive's `secrets` templates (and the generic `secret_discovery`) | nothing to add; the choice rule is 2d-3b's |
| `e_k`, `w_k` | PRESENCE or ALIBI, record | `presence_record` | ALIBI on a record must render with the same family as PRESENCE (a rule, not content) |
| `x_k` | PHYSICAL, record | nothing | **two** method-agnostic families, an incriminating one (the culprit's proof) and an exculpating one, with no method token and the same sentence shape |
| `y_k` | MOTIVE_CLUE, interrogate | `motive_clue` (generic mood sentences) | **per-motive hints**: a hint that points at its motive (the generic family cannot support a motive) |
| `l_k` | LIE, interrogate | `lie_alibi`, `lie_record`, `lie_accusation` | the **contradiction** text of a lie (`Fact.contradiction`) |
| `h_mj` true | TRACE, search | per-method `traces[].templates` | nothing |
| `h_mj` others | ABSENT_TRACE, search | the generic `absent_trace` | **per-trace absent templates** that name what is missing (the generic one cannot rule out a method) |
| `p_mj` | CLUE, search | the generic `small_clue` | **per-method clue templates** that support their method |
| `c_k` | CLUE (key), search | nothing | a key family with a `{who}` slot (it unlocks questioning a suspect) |
| `n_<kind>` | CLUE, location record | nothing | a neutral entry family per location-record kind |
| case | | role nouns and traits, location descriptions | the victim and an `intro` family that states the scene and the crime slot (the whole who deduction depends on them), the `smalltalk_allow` vocabulary, per-role persona style |

Notes the table leaves out: the families `alibi`, `witness_sighting` and `witness_hearing` have no fact the generator builds (every presence
and alibi fact is on a record source) and are unused until a stage builds spoken witnesses; `x_k` exists only for the culprit and the
opportunity suspects, and `c_k` only at depth 2; the 2d-2 list's "per-motive rule-out templates" is not needed, because the rule-out of a wrong
motive is that suspect's own `sec_k`, rendered from their motive's `secrets`.

This refines the list of the 2d-2 spec, section 10 (which also holds the pack-check hardening items). Whether `generate()` exposes only
the skinned case, how the leak lint treats the neutral families, and whether 2d-3b bumps `SKELETON_ALGO_VERSION` are 2d-3b's to decide.

## 11. Risks and open points

- **`generate_case` returns a case with no text until 2d-3b.** Anything that shows it to a player before then shows blanks. It is marked
  (`skin_rev = 0`), and the only callers today are developer commands and tests.
- **A flaky existing test** (`tests/cases/simulate/test_oracle.py::test_min_sources_is_quick_on_a_random_layout`, a 0.3 s wall-clock
  assertion) fails now and then on this machine, also on a commit without these changes (measured: it failed once in two runs on the base
  commit, and in two of three full-suite runs on the changed tree while passing alone). It is not touched here; rerun it alone before treating
  it as a regression.
- **The controller is a net that is never used on the castle** (mean 1.00 attempts, 12,000 cases). Its real exercise is the tests; the first pack
  or stage change that breaks the by-construction design will show up as retries in `smoke` before it shows up anywhere else.
- **`import gumshoe.cases` loads the generator** (section 6). Accepted for now.
- **Cases are listed in id order**, so every positional feature a player sees is the hash order. The 2d-4 statistics (culprit position,
  evidence-depth rank, text length rank) run on final cases and will confirm or refute what the chi-square tests here assert on 500 seeds.
- **Same shape every case** (2d-2 spec, section 11) is unchanged: variety is the roster, timeline, placement and depth.
- **A stage that raises is retried**, which can hide a pack that is infeasible for many seeds behind a mean attempt count above 1; `smoke`'s
  criterion (mean at most 2) is what catches it, and the pack-check hardening list (2d-2 spec, section 10) is the real fix.
- **Open for 2d-3b:** whether `skin_rev` or the skin hash joins the case id (section 6); the order of the skin and `skin_lint` attempts in the budget (a `skin_lint` call counts as an attempt, overview 2.3);
  whether the skin stage may fail with `fix_stage` skin only through `skin_lint`; dealing variants in fact-id order now that ids are hashes
  (the overview's 4.7 deals "in fact-id order so adjacent facts do not repeat": the order is pseudo-random, which is fine, but the first
  draft of 2d-3b should state it).

## 12. Review

One independent adversarial review (an agent that read this spec and the plan, ran the prototype and tried to break it). No blockers. What it
found, and what became of each finding:

| Finding | Disposition |
|---|---|
| `generate(presets=)` and `regenerate(presets=)` fail: the validator was not given the presets (`SPEC_MISMATCH`) | fixed (section 3); a test uses a widened `short` |
| `regenerate` silently drew another case when its one validator call failed | fixed: budget of one, raises (section 6); a test |
| the truth's ids repeat across presets and packs for a seed | fixed: `case.id` in the hash (section 4); a test |
| exporting `generate` shadows the subpackage `gumshoe.cases.generate` | fixed: exported as `generate_case`; a test (section 6) |
| a dangling reference from a stage output escaped as a raw `KeyError` | fixed: `assemble` raises `GenerationError` (section 4); tests |
| a stage's `GenerationError` stopped the run although a restart cures some seeds | changed: it is a retried attempt (section 5) |
| `smoke --seeds 0` was a pass | fixed: needs a case (section 7); tests |
| `replay(counters=)` did not validate counters | fixed: one `check_counters` (section 3); tests |
| the worked 10-line trace was not pinned; the random sequences never escalated; a "wrong controller" test did not run one | fixed (section 8) |
| surviving mutants: an unfixable warning, the skin stream key, the 20th attempt, `Location.requires` in `rename`, regeneration after a real fault | tests added (section 8) |
| dead code: `Retry.fail`'s redundant `k` reset, `record()` recomputing the error filter, an unreachable `case is None` check | removed, except three defensive raises that no test reaches: at the end of `build` (the type checker needs it), "the skin stage ran before assemble", and `id_map`'s "two entities share a neutral id" |
| `pack_versions` carried `skin_rev` while `case.skin_rev` is 0 | `pack_versions` has `skeleton_rev` only until 2d-3b |
| the case id did not change when only a later stage version changes | `generator_version` is in the case id (section 6) |
| spec header pointed at a section that held no review; survey table omissions | fixed (this section; section 10) |
| the plan's "prove it can fail" mutation for the salt loop raised `NameError` | fixed in the plan (`in ()`) |
| a lazy export so that `import gumshoe.cases` does not load the generator | not done, recorded (section 6, section 11) |

Verified correct by the review: the plan's code equals the prototype; ruff, format and mypy are clean; the red states and test counts replay as
stated; `Retry.fail` matches overview 2.3 rule for rule (including an escalation onto `assemble` or `skin`, unreachable on today's catalogue);
the budget has no off-by-one; clean-run semantics have no hole; ranks are uniform with and without a shuffle; a cross-kind id collision cannot
occur; every id-carrying list is re-sorted by the model; the CLI flow works. The fixes after the review were tested (mutation checks in the
plan) but **not** reviewed a second time.

### The second review

A second reviewer re-read this spec, the plan and the four commits after the fixes above, ran 42 of the plan's mutations (all failed their named
test), replayed the red states and test counts, tried adversarial controller scenarios (stage errors, budget boundary, restarts from `skin`
and `assemble`, `regenerate` of a retried case) and checked determinism under three `PYTHONHASHSEED` values. No blocker. What it found:

| Finding | Disposition |
|---|---|
| `regenerate` returned a different case when the preset table differs from the one the case was made with | fixed: `VersionMismatch("another spec")` (section 6); a test |
| the stamped case id ignored the spec (the same id for two specs) | fixed: `spec_hash` in the id (section 6); a test |
| the id holds only the skeleton hash, so a wording-only pack change keeps the id | recorded for 2d-3b (sections 6 and 11) |
| an `assemble` stage error wastes five attempts retrying a stage that draws nothing | accepted, documented (section 5) |
| "attempt = validator calls" in the plan's constraints and in `SmokeReport.attempts`' comment | fixed: an attempt is a validator call or a stage error |
| stale prose in the plan (the id formula, what `_Run` keeps, what `run` stops on, `SmokeReport.ok`, who resets `k`) | fixed |
| `budget=0` behaved as 1; "budget of 1 attempts"; an empty stage message lost the failure text; `smoke --seeds 0` gave no reason | fixed: `ValueError`, singular noun, class name as detail, "no case was made"; tests |
| `assemble`'s `except` wraps `build_case`, `id_map` and `rename`, so a deterministic bug in `rename` costs 20 attempts before it is reported | accepted: the message holds the `KeyError`; narrowing the `try` would split the one place the conversion exists |
| the four commits carried no attribution trailers | added when the commits were applied |

The fixes of the second review were tested (a mutation check each) but not reviewed a third time.
