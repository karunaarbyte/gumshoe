# Case Engine: Design Spec (sub-project 2)

Date: 2026-10-01
Status: **spec complete, awaiting user review.** Sections 1-6 approved and recorded. Next: user reviews this file, then the 2a implementation plan is written.

Parent spec: `2026-10-01-gumshoe-design.md`. Sub-projects 1a/1b (decision client, shadow stats) are built.
Design reviews: every section was attacked by an independent reviewer subagent; accepted findings are folded in below.

## 0. Settled decisions and principles

| Topic | Decision |
|---|---|
| Solving model | Player names **who** (culprit), **how** (method) and **why** (motive); all three right to win |
| Accusation input | Free text, mapped by Jev onto the case's canonical candidates: three choice questions in ONE batched call, one per axis, each option set = every candidate (label + aliases) plus a single `unclear` option. Criteria text is "the player affirmatively accuses this candidate", so negations, questions and hedges fall to `unclear`. On `unclear` the game lists the candidates the player may name under the gate and never says anything is "not in this case". Before an attempt is consumed the player confirms the resolved triple in display names |
| Accusation rules | **3 attempts, count-only feedback** ("1 of 3 right"), left as is by the user's choice (mildly exploitable via the who/why tie, accepted as fun). **The gate depends only on what the player holds, never on truthfulness:** `held_rule_out(Y)` = a held `rules_out` fact on Y that is not an exposed lie; `lead(X)` = any held `supports`/`proves` fact on X (lie-sourced or not); `permission(X)` = `lead(X)` OR every other candidate on that axis has a held rule-out; `warn(X)` = X has a held rule-out, and the same soft warning ("You hold an alibi or clue against X. Name them anyway?") appears whether the fact is true or a lie. Naming anyway consumes an attempt. X's own held rule-outs never block. If every candidate holds a rule-out, all are permitted with the warning. An identical repeated wrong triple says "you already tried that" at no cost. The simulator measures the blind-guess win rate of a "reads everything, then guesses" player per preset (reported and tuned, no hard ceiling in v1) |
| **No grind (principle)** | The game must not make the player grind through completeness when the answer is already clear. No mandatory exposure of lies, no mandatory reading of every record, no required "new fact" before an accusation or retry. Exposing a lie surfaces a contradiction and confirms a hunch; it never gates naming. The validator still requires every lie to be exposable (fairness). **Validator routes ignore lies; the player gate treats lies as visible facts and never requires exposure** |
| Story text | **Skeleton** (logic, deterministic from the seed) vs **skin** (prose). Skin from hand-written templates; an optional later LLM "dressing" pass may replace skin fields only |
| Case size | Presets `short`, `standard` (default), `long` with min/max sizes; fact counts are **derived** from structure (3.7). No silent clamping |
| Themes | Four theme packs as data: old castle, poor hut, city/town, spaceship. Build order: castle first to prove the format, then the other three |
| Generation | Constraint-first and truth-symmetric (Section 3); an LLM-written skeleton is **not** the default |
| Optional blurb path | The user pastes a story blurb; a reasoning model (local Ollama `gemma4` / `ministral`) produces a skeleton; it must pass the **same validator** (profile `imported`). Designed for now, **built after the first stable version** as its own sub-project |
| Frontend | Open, decided at sub-project 5. A richer frontend than plain HTML/CSS/JS is allowed (leading option: React + TypeScript + Vite + Tailwind) |
| Cost rule | Hosted Jev is billed: no live Jev calls in tests, the validator or the generator. Case-engine work is fully offline and deterministic. Live testing happens once, at the end of a batch of changes |

## 1. Scope and sub-project split

In scope: the `Case` model, the validator, an independent player simulator (test oracle), the generator, theme packs and skin.
Integration with the accusation parser, MCP tools and `PlayState` is Section 5 (pending).

Split (each gets its own plan, test-first, with a code review per task; see Section 6):
- **2a:** `core`, `model`, `rules`, `validate`, fixtures, mutation harness, `validate` CLI.
- **2b:** `play`, `simulate`, terminal `play` CLI.
- **2c:** pack format, loader, pack validation, castle pack.
- **2d:** generator stages, skin, retry, `generate`/`explain`, corpus statistics tests.
- **2e:** the other three packs (poor hut, city/town, spaceship).
- **later:** blurb-to-case (LLM skeleton + repair loop), LLM skin dressing.

## 2. Section 1: the `Case` schema (approved, with later amendments)

Immutable, JSON-serialisable Pydantic models, validated at construction. Skeleton fields are read by the validator and
are in the digest; skin fields are for players and are excluded from it.

```
Case: id, seed?, spec, theme, schema_version, origin (generated|imported), pack_ref?{id, skeleton_hash},
      generator_version? (null for imported), skeleton_algo_version, pack_versions, attempt, stage_attempts,
      skin_rev, skin_hash, smalltalk_allow (skin tuple copied from the pack; imported cases derive it)
  truth        who: SuspectId  how: MethodId  why: MotiveId
  spec         sizes AND its own floors/ceilings (difficulty, depth, ratios); the validator reads limits from here (see 6.3)
  start        locations[], suspects[], facts[]             (initially accessible / known)
  suspects[]   id (opaque), label, role, persona{traits, style, knows[]}, secret, requires[]
               + display_name, description (skin)
  locations[]  id, kind, aliases[], requires[], decorative   + name, description (skin)
  methods[]    id, label, aliases[]       (label: short and precise; with aliases it is all Jev sees)
  motives[]    id, label, aliases[]
  timeline[]   id, slot, actor, place, action                 (ground truth; >= 4 slots, pack-declared)
  facts[]      id, source, requires[], effects[], topic?,
               claim?{actor, place|record, slot}, truthful, speaker?, exposed_by[], exposure_hook?, timeline_ref[]
               + text (skin), contradiction? (skin, on lies; shown with the exposer; static engine fallback if absent)
    source   : search(location) | interrogate(suspect) | record(kind, subject)
    effects  : [(axis: who|how|why, candidate id, kind: rules_out | supports | proves)]
    requires : AND-only; fact ids that must be discovered first (also on locations and suspects as access gates)
  skeleton_digest = sha256(canonical JSON of every non-skin field, sorted keys, no floats)
PlayState (mutable, separate from the Case): discovered[], attempts, accusations[]
```

Rules baked into the schema:
- **Every candidate on all three axes, suspects included, has a short skeleton `label`** (hygiene-checked, in the digest,
  the only text Jev sees, plus aliases). `display_name` and `description` are skin. Dressing can never change a label.
- **Record sources are `(kind, subject)`**: `record(gate_log, steward)`. Secret records have subject = a suspect.
  Presence-projection records may have subject = a location or event and may hold facts about several suspects. Each suspect
  therefore has their own record source, so a single call can never dump every secret.
- **Effects:** `rules_out` is hard; `supports` is weak; `proves` is decisive. No fact proves on more than one axis. Effects name
  candidates of their own axis only.
- **Lies:** a fact with `truthful: false`. Its effects apply only while it is unexposed, and only to the player's own reasoning:
  **validator routes ignore lie effects entirely; the player gate treats a held lie as any other visible fact and never requires its exposure.** `exposed_by` must name truthful facts reachable without
  passing through the lie. `exposure_hook` names the exposer's source pair (kind, subject) and the lie text mentions that subject.
  **Ownership:** an exposer is "owned by the speaker" only if its source is `interrogate(speaker)`; a record *about* the speaker is allowed.
  Discovering an exposer immediately marks the lie exposed and surfaces the contradiction. Lie-sourced `supports`/`proves` never count as evidence.
- **No `priority`:** a search, interrogation or record lookup returns **all** newly available facts from its source; the validator caps
  facts per source at **4**. An empty `(kind, subject)` pair returns "nothing"; the tool router never enumerates pairs.
- **Ids** are engine-assigned short hashes (generated: of (seed, pool-key path); imported: an `intake` step maps the author's keys to hashed
  ids, so an author's `butler_culprit` never survives into a player-visible or digest-relevant field), never list indexes, so they are stable and
  do not leak. The digest is always computed by the engine and never trusted from input.
- **Saves store the finished case JSON**, never a regeneration.
- No time-of-day simulation, inventory or combat. The timeline exists to keep generated claims consistent.

## 3. Section 2: the validator (approved)

`validate(case, pack, profile) -> Report`: pure, deterministic, no I/O, no models, never raises on bad content. Returns **every** issue.
Profiles: `strict` (generated cases, all rules errors), `imported` (blurb path: group 9 statistical checks demoted to warnings) and `custom` (hand-built fixtures with their own spec). Pack-bound rules are listed in 6.3.

Each `Issue`: `code`, `severity`, `group`, `subjects[]` (ids), `axis`, `params` (machine fields), `hint` (enum + args, e.g.
`ADD_EXPOSER(lie_id, source)`), `spoiler: bool`. Reports are developer/internal only: never shown to a player and never fed to persona
or dressing models. Output is sorted by (group, code, subject, axis) and serialised canonically so the same input gives byte-identical
bytes (sets sorted before iteration, `PYTHONHASHSEED`-independent).

Rule groups (a failure in group 1 stops later groups; group 3 failing stops group 4):
1. **Structure and size caps** (before heavy work): ids unique, charset and sizes, no dangling reference (`requires`, `effects`,
   `exposed_by`, `speaker`, `source`, `timeline_ref`, `start`, `truth`), truth among its candidates, counts within spec and pack
   capacity, effects axis-correct, no multi-axis `proves`, start facts are not `proves`.
2. **Labels:** normalised (lowercase, stopwords, stemming); unique per axis and across axes; no token-subset or substring overlap;
   aliases do not collide; no collision with suspect-name tokens; comparable lengths; every candidate has at least one distinctive
   token after shared tokens are removed. Deterministic string logic only.
3. **Graph:** requires and gates are AND-only and form a DAG; ancestor closures `Anc(f)` computed once as bitsets (including the gates
   of f's source).
4. **Reachability by action:** fixpoint from `start`; orphans are errors unless `decorative`; at most 4 facts per source; every
   candidate on every axis has at least one reachable touching fact; every suspect has at least one reachable statement; every
   non-decorative location has at least one fact. No gate on `record(kind, j)` may require lie_j or anything depending on it.
5. **Lies:** structured claim; at least one exposer that is truthful, reachable, not owned by the lie's speaker (see schema), with the
   lie not in its ancestry; the claim points at the exposer's source pair; no lie exposes a lie; no circular exposure.
6. **Solvability, per axis:** using the effects of truthful reachable facts only: survivors are exactly `{truth}`; the truth is never
   ruled out; positive non-lie evidence exists (one `proves`, or two `supports` from distinct sources); `permission(truth)` holds under the
   shared play-module gate when only the route facts are held, and still holds after adding any subset of reachable lies.
7. **Timeline** (error in both profiles): no actor in two places in a slot; every `timeline_ref` resolves; truthful claims are
   consistent with it and lies contradict it; the culprit has opportunity; every wrong candidate with opportunity has a rule-out.
8. **Difficulty:** `Anc(f)` is a fact's ancestor closure. Per axis the **routes** are a reachable `proves` on the truth, or the cheapest
   truthful rule-out per wrong candidate (the elimination route, which satisfies clause 2 of the gate). **Exposers are not part of any route**;
   the gate ignores the target's own held rule-outs. `min_solution` = size of the cheapest union of closures (shared ancestors counted once);
   `depth` = longest gating chain in it; `actions` = distinct sources in it. Presets carry floors and ceilings on these, plus a ceiling on the
   decisive-to-total fact ratio. Within a pack, effective profiles must be componentwise monotone: short <= standard <= long. **No single point
   of failure:** removing any one non-start fact (and its dependents) must leave every axis deducible and `permission(truth)` intact, using the
   same gate function as the simulator (error in strict, warning in imported).
9. **Fairness** (warning in imported): facts, lies, secrets and exposures per suspect within +-1 by ownership (ownership = the `who`
   candidate named in effects, or the speaker); culprit not the unique extreme on any generator-controlled feature; per-axis
   candidates have the same fact counts and source kinds, with at most the truth's `proves` taking the rule-out slot; the truth's depth
   is not the unique max or min. Distribution statistics are corpus-level tests.
10. **Persona and secrets:** every secret referenced by a reachable fact; `persona.knows` is a subset of the facts the suspect can speak.
11. **Report:** canonical, sorted, deterministic.

Testing the validator: one known-good fixture case; per rule, a minimal mutation asserting the target code appears **and** the full issue
set equals a declared cascade set (include the culprit's secret record, which is both the culprit lie's exposer and the why `proves`);
a brute-force **player simulator** that drives the real play-module functions (`use_source`, the shared gate `permission`/`warn`, `accuse`; exposure only affects the warning and the held-rule-out definition) must agree with the validator
on ~1,000 generated seeds and on fuzzed mutations; the simulator also **measures the blind-guess win rate** of a "reads all records, then
guesses" player at each preset (reported and tuned, no hard ceiling in v1); a byte-identity test across two processes.

## 4. Section 3: the generator (approved)

`generate(seed, preset, pack) -> Case`: pure and deterministic.

**Streams.** Each stage draws from `Random(sha256(seed, spec_hash, stage_version, attempt, stage_label))`; never the global `random`.
Versions are per stage plus a global `skeleton_algo_version`. A shared seed is the code (seed, preset, pack, skeleton hash, algo version);
incompatible versions are refused with a clear message. Saves are unaffected.

**Truth-symmetric construction.** Build with the truth at canonical index 0, then apply **one random permutation of ids and order as the
last step**, so every positional feature is exactly uniform.
- Every suspect gets exactly one lie plus an exposer; every suspect's lie claims a false position at the crime slot.
- Every candidate on every axis gets same-shape evidence: a wrong candidate `{rule-out, supports}`, the truth `{proves, supports}` (the
  `proves` takes the rule-out's slot, so counts are equal).
- One record per suspect, `record(kind, that suspect)`, serves three roles: reveals that suspect's secret, exposes that suspect's own lie,
  and supplies the why-axis evidence (for the culprit it is the why `proves`). It holds at most 4 facts (the secret fact plus up to 3 free).
- Evidence depth targets are drawn independently of which candidate is the truth.
- **Motive candidates number exactly the suspects (V = S)**; each suspect's secret realises a distinct motive type. (A shorter motive list
  would make the one unlinked suspect never the culprit.) The why axis therefore tracks the who axis, as in most mysteries; its difficulty
  comes from finding the suspect's gated secret record, ruling out wrong motives, and a hidden random suspect-to-motive matching (4.11).
- Red herrings are the wrong candidates' `supports`; their ratio is derived. The tuning knob is `r`, supports per candidate.

**Stages (frozen dataclass outputs; `generate` is a fold):** effective spec -> roster -> truth -> timeline -> facts -> placement -> gating
-> permute -> skin (Section 4 below).
- **Roster:** a constraint-satisfying draw: sample methods first, ensure the roster covers every sampled method's `needs_location_kinds`
  (for all methods, not only the truth's), then fill. Sampling is by rendezvous hashing. Shuffle everything before the truth is chosen.
- **Timeline:** at least 4 slots. Each suspect's row is drawn independently. The culprit is at the scene in the crime slot; the spec says
  how many wrong suspects also have opportunity. Alibis and presence records are timeline projections; physical traces are pack-defined
  (method -> trace -> allowed location kinds). A truthful witness claim requires co-location with the subject; a liar's claim contradicts
  the timeline; framing lies are generated symmetrically.
- **Facts:** per axis, the symmetric evidence above. Wrong suspects with opportunity get a physical rule-out instead of an alibi.
- **Placement:** greedy assignment with swap repair; at most 4 facts per source; ownership +-1. Processing order is shuffled with a
  role-independent stream. One evidence shape per axis; source kinds sized to capacity at pack load.
- **Gating:** layered construction: depths assigned first, edges between consecutive layers, so depth is exact; decisive facts and decoys
  share layers; in-degree and chain length capped; gated-fact share within a band. The `proves` route and the elimination route must have
  **disjoint closures** by construction, and no gated location may hold both a `proves` and a rule-out of the same axis. No gate may make
  a suspect's record depend on that suspect's own lie.
- **Permute:** ids derive from pool keys with neutral slot numbers; fact, timeline, `requires`, `effects` and `exposed_by` lists are
  shuffled or sorted; each entity draws templates from a stream keyed by its pool key; the canonical-to-final id map is applied only at output.

**Validation and retry.** Run the `strict` validator. Each issue code maps to its **earliest possible fixing stage**; the generator restarts
from that stage with a new stage stream, up to 5 retries per stage, then escalates to the previous stage. A whole-case restart (up to 20
attempts) is the backstop; after that `CaseGenerationError` carrying the last report. All stage-attempt counters are stored in the case
metadata so replay is exact. Repair hints are logged for diagnostics; targeted repair is a later optimisation if retry rates are high.

**3.7 Derived presets.** Fact counts follow from structure. With S suspects, M methods and V = S, total facts T = 5S + 2M.

| Preset | Suspects | Methods | Locations | Record kinds | Derived facts |
|---|---|---|---|---|---|
| short | 4 | 3 | 3 | 2 | ~26 |
| standard (default) | 5 | 4 | 5 | 2 | ~33 |
| long | 7 | 5 | 6 | 3 | ~45 |

Approximate play time: short 15-20 min, standard 25-35 min, long 45-60 min.

**Presets and packs (replaces the earlier "clamp and compensate").** A preset defines a **min and max for each size**. The effective size is
`min(preset max, pack capacity)`, and a pack **supports** a preset only if its capacity reaches every minimum. Pack load computes the
supported presets and fails with a clear message when a pack claims one it cannot host (for example *"hut: preset 'long' unsupported: needs
suspects=7 (max 5)"*); there is no silent clamping. The UI offers only supported presets and shows the effective numbers ("5 suspects, about 33
clues"). Preset ranges must not overlap on suspects, methods or locations. Monotonicity is required within a pack, not across packs. Demand is
checked at the **effective** size, per source kind: demand <= 0.8 x 4 x sources of that kind.
Capacity uses *guaranteed* sources: S interrogate + L search + S secret record pairs, plus declared location/event record pairs. Example
(hut): short S=4, L=3 gives 11 sources (35.2 allowed vs 26 needed); standard S=5, L=4 (hut max) gives 14 sources (44.8 vs 33); `long` is
unsupported (needs S=7, L=6; max 5 and 4).

**Pack-load smoke test.** 200 seeds per (pack, supported preset) with the strict validator and the simulator: mean attempts <= 2, max <= 10;
report the failure distribution per rule code (not just the mean).

**Generator tests.**
- Fixed seed list 0..999 per pack: chi-square on features (culprit position, facts-per-suspect rank, lie count rank, depth rank, text-length
  rank, culprit motive type vs role) with Bonferroni correction, a deterministic regression snapshot; plus a slower variant on random seeds
  behind a `slow` marker. A dev-only scipy or hand-rolled critical values for the statistics.
- Trivial classifier per feature ("pick the suspect with max/min of f") must score within chance + 3 sigma.
- Strict validator and simulator pass on every generated case; regeneration is byte-identical across processes.
- Golden snapshots of each stage's output digest for 5 seeds per pack; per-stage invariant tests (timeline: no double-booking, culprit at the
  scene, opportunity count equals the spec).
- Developer tools: `replay(seed, preset, pack, upto=stage, override={stage: output})` and a spoiler-marked `explain(case)` (truth, closure of
  each deciding fact, cheapest route, per-suspect feature table, lie/exposer pairs, last failed issues). Never reachable from a player surface.

## 5. Section 4: theme packs and skin (approved, with fixes from the final review pass)

**4.1 Format.** A pack is a TOML file in `src/gumshoe/cases/packs/<id>.toml` (stdlib `tomllib`), validated into a Pydantic `Pack`. Errors report
key paths with did-you-mean (`castle.toml: methods.dagger.traces[0].location_kind -> unknown kind 'crypt'; known: [chapel, keep, ...]`).
Presets are global; a pack declares `[capacity]` only. Pack-load validation, in order: schema, closed references, template slots and rendering,
label hygiene across the whole pool, plausibility rules, capacity vs demand at every effective size, preset monotonicity, motive matching (4.11),
then the smoke test.

**4.2 Pool entries and templates.** Pool entries are tables (`text`, `article`, `plural`, `pronoun`, `proper`). Each fact-template family has a
fixed small placeholder set (`{who}`, `{who.subj}`, `{who.poss}`, `{item.a}`, `{item.the}`, `{place.in}`, `{time.phrase}`; a leading `^`
capitalises). Time slots supply ready adverbials (`at`, `during`); facts are written in the past tense; there is no template language. Variants
per family >= the largest per-case count (5 for standard, 7 for long) and a case dedupes identical rendered sentences. Pack load renders the
cross product (or a capped sample) and rejects doubled words, unresolved `{`, double spaces, "a" before a vowel, and capitals mid-sentence.
Families store `claim_slots` so lints know which values must survive.

**4.3 Plausibility fields.** `roles.<id>.record_kinds` (kinds the role can plausibly appear in) and `roles.<id>.motive_types` (allow-list, at
least 3). Record kinds carry `subject` (suspect|location|event) and `medium` (written|token|oral), so a hut can use a carved tally or gossip at
the well. `scene_types.<k>` lists `location_kinds`, `allowed_methods` and `allowed_trace_kinds`. Pack load rules: every role has at least one
record kind and at least 3 motive types; every motive type has a record kind for some role; every scene type has a legal crime location kind;
`min_slots` is enough for the co-location rule.

**4.4 Pool-level leak rules (checked at pack load).** Every wrong candidate method must be possible at the chosen scene type, and each method is
allowed in >= 2 scene types; a candidate's label tokens appear only in its own entries, across **all** pack text (location descriptions and role
traits too); a motive's secret text never reuses its label; trace templates per method are equal in count and within +-20% in length.

**4.5 Leak lint.** `tokens(c)` = stemmed non-stopword tokens of the label and aliases minus tokens shared with any other candidate. A candidate's
*touching* facts are those the **evidence gate's** touching function returns (reused so they cannot drift) plus the lie and exposer whose claim
names it. Per case, a stray mention of a method or motive token in a non-touching fact is an error (suspect names are exempt); warn if the truth's
total mention count is the unique max or min. Corpus tests (fixed seeds, Bonferroni): phrasing variant vs truth role, text length vs truth role,
mention-count rank, and `proves` vs rule-out facts using identical template families.

**4.6 Label vs display name.** Every distinctive token of a skeleton label must appear in its display name (checked on the template skin at pack
load and after any dressing). Each candidate has accepted spoken forms (surname, role, title) that become aliases and go through label hygiene.
Persona intros use the label tokens at least once. This keeps "Hale did it" mappable by Jev.

**4.7 Skin determinism.** Skin streams are keyed by the fact's neutral id. Variants are dealt by shuffling the variant list once per
(family, case) and dealing in fact-id order, so adjacent facts do not repeat. Skin never depends on effect kind.

**4.8 Versioning.** Pool sampling uses rendezvous hashing (top-k by `hash(seed, pool_key)`), never file order, so adding a name only changes the
cases where it ranks in. A pack carries `skeleton_rev` (pools, kinds, capacity, trace structure, claim slots) and `skin_rev` (wording). Wording
edits bump `skin_rev` only; the seed code includes a skeleton hash; saves store the finished JSON plus both revs and a skin hash. A skeleton change
bumps `skeleton_rev` (keep old pack files frozen if old seeds must stay playable).

**4.9 Dressing (later, optional).** An LLM pass may replace only skin fields (`display_name`, `description`, `text`, intro). It is accepted only if
label hygiene, the leak lint, the label/display-name rule and a claim-fidelity lint (each fact's text contains its rendered claim-slot values) all
pass; otherwise the template skin is kept. The skeleton digest must stay identical.

**4.10 Presets and capacity**: see 3.7 above.

**4.11 Suspect-to-motive matching.** V = S. Each suspect's secret realises a distinct motive type, constrained by role allow-lists. Pack load runs a
Hall check proving a perfect matching exists for every roster the pack can produce, and requires the maximum marginal P(motive | role) <= 0.5.
At generation, enumerate all valid matchings by backtracking (at most 7! = 5,040), sort them, and pick one uniformly by index from the stream; this
is drawn over the whole roster, independent of the culprit, before the truth index is chosen. (Rejection sampling over permutations would succeed
about 3 times in 10,000 for 7 suspects.)

**4.12 Packs and content.** Four packs, written by the LLM at authoring time for the user to review. Castle first.
- **Castle:** great hall, chapel, keep; visitor ledger and gate log; steward, priest, cook.
- **Poor hut:** hearth, loft, yard, well; scarce records (tally sticks, kin letters, gossip); small capacity (supports short and standard).
- **City/town:** streets, tavern, docks; police files, ledgers.
- **Spaceship:** bridge, engine room, med bay, airlock, galley; airlock and comms logs.
Minimum viable castle: about 250 text items (10 names, 8 roles, 6 location kinds, 3 record kinds, 6 motive types, 6 methods, about 12 template
families at 5 variants), roughly 1-2 days of writing plus review; on the order of 10^5-10^6 structurally distinct cases.

**4.13 Pack TOML skeleton (castle, structure only).**
```toml
[meta]
id = "castle"; name = "Old Castle"; skeleton_rev = 1; skin_rev = 1; slots = 4

[capacity]
max_suspects = 8; max_locations = 7; max_record_kinds = 3

[[slots_def]]
key = "vespers"; at = "at vespers"; during = "during vespers"

[location_kinds.chapel]
names = [ {text = "Chapel of St. Anne", article = "the", proper = true} ]
desc = ["{place} smells of cold wax."]

[scene_types.murder_in_chapel]
location_kinds = ["chapel"]; allowed_methods = ["candlestick", "poison_wine"]; allowed_trace_kinds = ["blood", "residue"]

[record_kinds.gate_log]
subject = "suspect"; medium = "written"
presence = ["The gate log shows {who} {time.at}."]

[roles.steward]
names = [ {text = "Edmund", pronoun = "he"} ]
record_kinds = ["gate_log"]; motive_types = ["debt", "inheritance", "jealousy"]   # >= 3
traits = ["precise", "nervous"]; speech = ["formal"]
spoken_forms = ["Edmund", "the steward"]                                           # become aliases

[motive_types.debt]
label = "to cover a debt"; aliases = ["money owed"]
secret = ["{who} owes a moneylender more than {who.subj} can pay."]
reveal_record = "gate_log"
ruleout = ["{who} had no need of coin."]

[methods.candlestick]
label = "struck with a candlestick"; aliases = ["bludgeoned"]
needs_location_kinds = ["chapel"]
[[methods.candlestick.traces]]
trace_kind = "blood"; source_kind = "search"; location_kind = "chapel"
text = ["A dent in the stone floor under the altar."]
absent = ["The altar stones are unmarked."]

[families.alibi]
claim_slots = ["actor", "place", "time"]; plural_ok = false
variants = ["{who} was {place.in} {time.during}.", "..."]   # >= 7 for long
```

## 6. Section 5: integration (approved)

**5.1 One shared rules module.** `cases/play/` (part of 2a): immutable `PlayState` (discovered facts, derived exposed set, attempts,
accusation history, status playing|won|lost, `case_digest` so a state cannot be paired with another case; no turn counter) and pure functions
`available_facts`, `use_source(case, state, source) -> (state', SourceResult)`, `permission`/`warn` (the gate, 5.4), `accuse`, `notebook`,
`case_brief`, `reveal`, `give_up`. Same inputs give the same outputs; discovered facts only grow; attempts never exceed 3. The validator
simulator drives these functions; the validator's own reachability and exposure code stays independent (closure bitsets, no import of play), so
a validator-vs-simulator disagreement is a bug in one of them. Three hand-built golden cases test the play module directly.

**5.2 Spoiler boundary enforced by types.** The skeleton `Case` never reaches a player surface or the agent loop. The agent loop gets a
`GameSession` handle (Case and PlayState held server-side) whose methods return only `play.views` models: `PlayerCaseView`, `FactView(handle,
text, speaker?)`, `ContradictionView`, `SourceResult(kind, status ok|nothing_new|locked|unknown, new_facts, contradictions, opened)`,
`NotebookView`. Views never carry `truthful`, effect kinds, ids (players get per-save opaque handles `hash(save_salt, id)`), or ordering that
follows generation order (`new_facts` sorted by neutral id). The notebook groups by source and "relates to X", never by effect kind. An
architecture test forbids tool and UI code from importing skeleton types or the validator. Saves contain the full skeleton and are documented as
spoiler-bearing on disk, kept outside any path agent tools can read; seed codes are shown only after the game or on an explicit "share".

**5.3 Tool semantics (thin MCP wrappers, sub-project 3).** Locations and suspects are all known from the start; gated ones answer `locked`
(revealing only that a gate exists). `search(location)`, `interrogate(suspect)` and `check_records(subject, kind?)` return ALL newly available facts
from their source(s), at most 4 per source; an empty or exhausted valid pair returns `nothing_new`, and `unknown` is reserved for entities not in
the case. `check_records` without a kind aggregates the record kinds about that subject, says which kinds contributed and caps its display. An
interrogation is one "sitting". Calls are idempotent. A discovery returns `opened: [sources]` that now have newly available facts, so the player
never re-queries to see whether something unlocked. **A contradiction is emitted only when BOTH the lie and its exposer are discovered, at the
later discovery**; if the exposer is found first, the lie is shown already marked contradicted when it is later discovered; no view ever names an
undiscovered fact. Lie facts carry a skin `contradiction` text (written from a pack template family at generation, stored in the Case), with a static engine fallback.

**5.4 Accusation flow.** (1) One batched Jev call (`accusation_questions(case)`: three `choice` questions labelled with their axis, options =
every candidate by label + aliases plus `unclear`, one-letter keys shuffled deterministically from (case id, number of accusations so far)).
(2) Pure `interpret(result)`: a part is a Candidate only if the top option's probability >= a high threshold AND its margin over the runner-up
>= a margin threshold (start: top > 0.6, margin > 0.25, biased toward asking); a near-tie or low confidence is `unclear`. (3) Any `unclear` part
gets a reply listing the candidates the player may name under the gate. (4) Permission check per part with the gate in the decisions table;
warnings are collected. (5) One combined confirmation shows the resolved triple in display names plus any soft warnings. (6) `accuse(...,
confirmed=True)` rechecks permission and the repeat-triple rule at call time, counts correct parts, consumes one attempt, returns the count only;
three correct is a win, the third miss a loss (then `reveal`). `give_up` ends the game with a reveal. Parser thresholds are tuned **offline** on
about 150 recorded Jev answers (ambiguity, negation, hedges, two labels in one phrase) taken once during the live pass of sub-project 4, never in
the per-task loop (about 150 billed calls; to be agreed before running).

**5.5 PlayState persistence.** A save = the finished case JSON + PlayState JSON + versions. The notebook is a derived view. Evidence-board links
the player draws are client-owned UI state, not engine state.

**5.6 Personas.** A pure `persona_brief(case, state, suspect_id)` for the agent loop: traits and style, the statements the suspect can speak
that the player has unlocked (including the suspect's own lie once unlocked), and **reticent topics derived from the lie's claim** (claimed
place and time phrase), the same shape for every suspect. **No secret text and no truth fields**: a secret reaches the player only through the
gated record fact. The culprit's brief comes from the same function. Dialogue is a paraphrase of the unlocked fact texts; the LLM may not invent
clues. **`reply_check(case, state, suspect, player_text, reply) -> ok|violations`** runs inside the engine (free, deterministic, pass/fail only,
violations logged by category, not token): it flags any candidate label token (all candidates, all axes) that does not appear in the player's
own messages, the unlocked or discovered fact texts, the `PlayerCaseView` text, or the pack's neutral small-talk words (tuned on a corpus of
persona replies at pack-authoring time). Fixed state machine, no loop: first reply, one regeneration with a local model, then a paraphrase fallback
dealt from several variants per suspect (same dealing rule as the skin). No hosted model check per dialogue turn.

**5.7 Boundaries.** The agent loop (sub-project 4) owns routing with Jev (intent, target choice), calling tools, persona dialogue and narration.
The case engine owns everything above and makes no model calls. Jev calls per player turn: routing (batched, existing) plus one batched call per
accusation attempt; the confirmation step adds none.

**5.8 Tests.** Property tests with random action sequences against generated cases: functions never raise, state is monotone, attempts <= 3, no
player-visible field contains a truth id or label while the game is playing, a non-permitted accusation never consumes an attempt,
`permission(truth)` holds at the end of every winning route, calls are idempotent, byte-identical outputs for identical inputs. Parser tests with
fake Jev results (ambiguity, `unclear`, near-ties, shuffled keys). Contradiction-order tests (exposer first, lie first). `reply_check` tests
including a legitimate other-candidate token inside an unlocked statement.

## 7. Section 6: module layout, plans, blurb hook (approved)

**6.1 Layers** (package `src/gumshoe/cases/`; one public API; layers enforced by `tests/test_architecture.py`, one rule per edge):
```
core/      canonical JSON, hashing and ids, tokeniser, stemmer, label-hygiene predicates, FixStage enum; imports nothing else in cases/
model/     data only: Case, Fact, ..., Pack type and its skeleton-hash function, spec and presets, Held = frozenset[FactId];
           every field classified skeleton or skin in ONE table, with a test
rules/     ~100 lines of pure semantics over (case, held, ...): exposed, lead, held_rule_out, permission -> Permission(allowed, warn); golden tests
validate/  rule groups, Report/Issue, profiles; its OWN graph algorithms (closures, fixpoint, routes)
play/      PlayState (its `discovered` is a `Held`), use_source, accuse, views, GameSession, reply_check, accusation_questions, match_label
packs/     TOML loader and pack validation (imports core, model, rules)
generate/  streams, stages, skin, replay/explain (imports validate for strict retry)
simulate/  brute-force player simulator (imports play and validate)
tools/     CLIs
```
Import order: `core < model < rules < {validate, play, packs} < generate < simulate < tools`. Only `play/` may import `gumshoe.decider` (types only,
to build the three accusation questions); nothing else under `cases/` does. Outside `generate/streams.py` and `tools/`, an ast test bans `random`,
`time`, `datetime`, `uuid`, `os.environ`, builtin `hash` and `open`. Independence applies to **algorithms, not definitions**: `validate` keeps its
own closure and reachability code and `play` its own state iteration, while the gate is a shared *specification* in `rules/`; gate semantics are
covered by golden tests, not by simulator-vs-validator agreement. **Monotonicity property** (property-tested): with the route facts held,
`permission(truth)` cannot be lost by adding further facts or lies (a lie's rule-outs only add to other candidates' held rule-outs; exposing a lie
removes only lie rule-outs), so the validator checks the route facts alone.

**6.2 Plans.** Each test-first with a code review per task, no live Jev. Before 2a an **issue-code catalogue** is written as a spec appendix.
| Plan | Content | Ends with |
|---|---|---|
| 2a | core, model, rules, validate, fixtures, mutation harness, `validate` CLI | a hand-built case that validates and every rule mutation-tested |
| 2b | play, simulate, terminal `play` CLI | a playable fixture; simulator agrees with the validator on it and its mutations |
| 2c | pack format, loader, pack validation, castle content | a valid castle pack |
| 2d | generator stages, skin, retry, `generate`/`explain`, corpus tests | 1,000-seed validator/simulator agreement and statistics tests |
| 2e | the other three packs | all four themes |
The validator comes before the generator; each rule code declares a default `fix_stage` so the generator's retry does not invent its own mapping.
Groups 4, 5, 6 and 8 are **provisional until 2b** (the 2a mutation expectations are written by the validator's author), mitigated by a naive
reference reachability (~50 lines, in `tests/`) with property tests on small random cases.

**6.3 Decisions made now (costly to change later).**
1. **A Case is self-contained for play.** Display names, descriptions, texts, intro, contradiction text and the `reply_check` small-talk vocabulary
   (`smalltalk_allow`) live in the Case; nothing is looked up from a pack at play time. `origin` and an optional `pack_ref` select the rules.
   `skin_rev` and `skin_hash` are stored; `origin`, `pack_ref` and all skin fields stay out of the skeleton digest, which includes `schema_version`
   (`generator_version` is nullable for imported cases). A saved case keeps its stored skin: a pack skin edit changes only regenerated seeds; the
   byte-identity test pins `skin_rev`. The static contradiction fallback lives in code and is versioned with `schema_version`.
2. **Engine-assigned ids** with the `intake` step above.
3. **`spec` carries its own floors and ceilings;** the validator reads limits from `case.spec` (presets and the `derive_spec(preset_name, pack)`
   function live in `model/spec`), so a small hand-built fixture can be known-good under profile `custom`.
4. **Pack-bound rules** (the only ones needing a `Pack`): (a) group 1 capacity vs the pack and its scene types; (b) group 4 per-kind capacity (the
   0.8 check); (c) plausibility (role record kinds, motive allow-lists, trace kinds per scene type); (d) **`SPEC_MISMATCH`**: `spec ==
   derive_spec(preset_name, pack)`, so a generated case cannot validate itself with a lax spec; (e) **`PACK_MISMATCH`**: `pack_ref` matches the
   supplied pack's id and skeleton hash. Everything else runs without a pack. `validate(case, pack=None)` on a generated case under `strict` emits
   one `PACK_RULES_SKIPPED` issue (error in strict, info in imported) listing the skipped codes, still runs all pack-free rules, and never passes
   silently. The strict known-good fixture uses a small `Pack` built in Python (the type lives in `model/`; the loader arrives in 2c).

**6.4 Blurb hook (built later).** Schema = plain serialisable data; validator returns every issue with a hint; profile `imported`; `pack=None`.
Later flow: local Ollama reasoning model drafts a skeleton as JSON against the schema -> `intake` (keys to hashed ids, engine digest) -> Pydantic
parse -> `validate(imported)` -> bounded repair loop (~5 rounds) feeding issues back -> skin -> saved, playable. The blurb schema must carry what the
generator normally fills: structured claims, a timeline (group 7 still applies to structured claims), `start`, access gates, typed record
`(kind, subject)` sources, `exposure_hook`, labels and aliases. All local; Jev only at play.

**6.5 Terminal `play` CLI (2b).** Menu-driven numbered choices (locations, suspects, accusation parts from the nameable set); an optional
typed-label path goes through ONE deterministic `play/match_label(axis, text)` producing the same `ParsedAccusation` as the Jev `interpret`;
both feed `describe_accusation` and `accuse(confirmed=...)`. It needs: a `PlayerCaseView` listing known locations and suspects with display names
and stable numbers, `SourceRef` display labels, a notebook text renderer, `opened`/`locked` messages, and `check_records` listing contributing
kinds. The player CLI imports only `GameSession` and views (plus `reveal` after the end); `explain` and import tools live in a separate dev entry
module (architecture rule). The Jev parser later reuses the same labels and aliases for its option criteria.

**6.6 CI hygiene.** The cases rules go into `tests/test_architecture.py`; mypy strict with the pydantic plugin; ruff; frozen models with tuples,
never sets; a `slow` marker beside `live` for corpus, smoke and 1,000-seed tests; fixtures built in typed Python (mypy catches schema drift) with a
committed JSON snapshot and a builder-equals-snapshot test, round-trip tests and a golden digest; hand-written canonical JSON (sorted keys, ints
only, NFC strings, order-significant lists vs id-sorted lists declared per field), independent of Pydantic's order; a subprocess test under two
`PYTHONHASHSEED` values comparing Report and Case bytes.

**6.7 Issue-code catalogue (appendix, written before 2a).** Fields per code: `code`, `group`, `severity_strict`, `severity_imported`,
`fix_stage` (FixStage), `hint` (enum op + typed `params`), `subjects` (id kinds), `spoiler`, `requires_pack`, `stops_later_groups`, a message
template, and `mutation` (the named fixture mutation that triggers it). Enums to pin in the 2a plan: `Axis` {who, how, why}; `EffectKind`
{rules_out, supports, proves}; `SourceKind` {search, interrogate, record}; `RecordSubjectType` {suspect, location, event}; `Medium` {written,
token, oral}; `FactKind`/family list; `ClaimKind` {presence, record_ref}; `Origin` {generated, imported}; `Profile` {strict, imported, custom};
`Severity`; `FixStage` {roster, truth, timeline, facts, placement, gating, skin, assemble, pack, none}; hint ops {ADD_EXPOSER, RAISE_DEPTH,
REMOVE_EFFECT, RELABEL, MOVE_FACT, ADD_FACT, REPLACE_TEMPLATE, DROP_CANDIDATE, ...} with params schemas; slot representation (index vs key);
access-gate representation (`requires: tuple[FactId, ...]` on locations, suspects and record pairs); `SourceRef` shape; id format (entity prefix,
hex length, collision handling); canonical JSON rules; digest algorithm (sha256 with a domain-separation prefix) and the exact skeleton field list
including the pack skeleton-hash fields.

## 8. Open items

- Pin the enums, catalogue and formats listed in 6.7 in the 2a plan (and the Report schema).
- Exact `r`, depth ranges and gated shares per preset: fixed in the 2d plan with tests.
- Blind-guess win rate of the "reads everything, then guesses" player: measured by the simulator in 2b; tune the structure if it is far too high.
- Parser thresholds: tuned offline on ~150 recorded Jev answers during the live pass of sub-project 4 (about 150 billed calls; agree before running).
- Whether and when the optional LLM dressing and the blurb path are built: after the first stable playable version.
- Frontend technology: decided at sub-project 5.
