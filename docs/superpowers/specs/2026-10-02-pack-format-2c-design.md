# Pack format, loader, pack validation and the castle pack (sub-project 2c)

Status: design, written 2026-10-02 after brainstorming. Extends `2026-10-01-case-engine-design.md` (sections 4 and 6.2) and
closes the items 2a deferred. Not committed: `docs/` is git-ignored and committed by hand.

## 1. Intent

2a gave a validator and 2b a playable engine, but a `Pack` exists only as a minimal Python type, so no case is tied to a real theme.
2c makes a pack a real, validated, loadable file, so that the 2d generator has a trusted input. 2c ends with **a valid castle pack**
(spec table, 6.2) and the case validator able to check a case against it.

Success criteria:
1. `python -m gumshoe.cases packs check castle.toml` exits 0 with no issues on the castle pack.
2. Every pack-load code has a mutation test with an exact expected cascade (same discipline as 2a); every defect in a mutated pack
   is reported in one run, with a key path and a suggestion.
3. A case that uses a location kind, trace kind or claim record kind the pack does not allow is rejected by `validate` (group 11).
4. Loading never raises on bad content, only on an unreadable file.
5. All existing tests keep passing (the 2a golden files are regenerated once for `Fact.trace_kind`, section 3); ruff and strict mypy stay clean.

Decided with the user: full castle content in 2c (about 250 items, written by Claude in reviewable chunks, approved chunk by chunk);
pack codes use plain names like the case codes (no prefix).

Out of scope: the 200-seed smoke test per (pack, preset) (needs the 2d generator), the LLM dressing pass, the other three packs (2e).

## 2. Layers and boundaries

- `model/pack.py` keeps the `Pack` type (data only) and its skeleton hash. It grows (section 3).
- New package `src/gumshoe/cases/packs/` (spec 6.1: imports core, model, rules only; never `validate`, `play`, `generate`):
  `issues.py` (`PackIssue`, severity, ordering), `catalogue.py` (pack codes), `loader.py` (read, parse, schema), `check/` (one module
  per stage), `runner.py`, `castle.toml`, and `__init__.py` as the public face (`load_pack`, `check_pack`).
- **No file access in `packs/`.** `tests/test_architecture.py` bans `open`, `os` and `.read_text()`/`.read_bytes()` outside `tools/`
  (determinism rule), so `load_pack(data: bytes) -> LoadResult(pack | None, issues)` is pure, like `load_case(bytes)`. `tools/` reads
  files and exposes `load_builtin_pack(name)` for the bundled `castle.toml`. The generator (2d) takes a `Pack` argument, so it never
  needs file access either.
- `validate` and `packs` are sibling layers and cannot import each other, and `validate.report.Issue` is case-shaped (axis,
  fix stage, spoiler), so `packs` has its own small `PackIssue`. The layer test in `tests/test_architecture.py` gets a rule for the
  new edges.
- `tools/` gets `packs check <file>` next to `validate`, `simulate` and `play`. `tools` may import `packs`.
- Code names are plain and unique across both catalogues: a test asserts the two catalogues share no code. (The case catalogue already
  owns `SLOTS_TOO_FEW`, `ROLE_UNKNOWN`, `SCENE_NOT_IN_PACK` and similar, so pack names are chosen to differ, for example `UNKNOWN_ROLE`.)

## 3. The richer `Pack` model

`Pack` stays frozen (`extra="forbid"`), lists stay sorted, so equal packs serialise identically. New content, all structure or pools:

- `slot_defs`: key, `at` phrase, `during` phrase (`slots` count stays; `len(slot_defs) >= slots`).
- `location_kinds`: key, name pool entries, description templates.
- `record_kinds`: key, `subject` (suspect | location | event), `medium` (written | token | oral), presence templates.
- `methods`: key, label, aliases, trace kinds each with the allowed location kinds and its trace templates.
- `roles`: key, name pool entries, traits, `record_kinds`, `motive_types` (existing fields kept).
- `motive_types`: key, label, aliases, secret templates.
- `families`: template families (id, kind, `claim_slots`, variants).
- `Entry`: `text`, optional `article`, `plural`, `pronoun`, `proper`.
- `presets`: the preset names the pack claims to host (spec 3.7: a pack that claims one it cannot host fails at load, naming the shortfall).
- Existing `Capacity`, `SceneType`, `RoleDef` stay; `Capacity` already has `max_methods`.

The skeleton hash is computed from an explicit projection (`Pack.skeleton_view()`), not `model_dump` minus fields, because wording sits
inside nested tables. Included: ids and keys, capacity, `slots`, `presets`, scene types, role and motive allow-lists, candidate labels
and aliases (they are skeleton), pool membership by key, trace structure, and `claim_slots`. Excluded: `skin_rev`, the text of template
variants and of descriptions, trace and secret templates, and the number of variants (dealing is skin, spec 4.7). Changing a variant's
wording or adding a variant must not change the hash; adding a name, kind, trace kind or claim slot must. Both directions are tested.

**Case model change (decision, flag for review).** `model_dump` serialises `None`, so the new field changes every case digest. The case's trace facts carry no trace kind today (`Fact.topic` is used for
interrogation topics and is not overloaded). To check trace kinds, add `Fact.trace_kind: str | None = None`, allowed only on
`TRACE` and `ABSENT_TRACE` facts. It is a skeleton field, so the 2a golden files (`tests/cases/golden/manor_small.*`) and fixture hashes are
regenerated once, with the fixture's trace facts given real trace kinds; `schema_version` stays 1 because no case has been saved yet
(nothing is generated or imported before 2d). Two small case rules go with it: `TRACE_KIND_ON_NON_TRACE` (group 1, always) and
`TRACE_KIND_MISSING` (group 11: with a pack, a `TRACE` or `ABSENT_TRACE` fact must name its trace kind, else it would dodge the rule).
Alternative if you prefer not to touch the case schema: drop the trace-kind case rule from 2c and check trace kinds only inside the
pack (stage 5), moving the case-side rule to 2d with the generator.

## 4. Pack issues

`PackIssue(code, severity, path, message, suggestion)`:
- `path`: TOML key path, for example `methods.dagger.traces[0].location_kind`.
- `suggestion`: did-you-mean or fix text, for example `unknown kind 'crypt'; known: chapel, keep, hall`. Computed by edit distance over
  the known keys, deterministic.
- Severity: error | warning | info. Sort key: stage, code, path, message.
- Catalogue entry per code: code, stage, severity, one-line meaning, and the message template. A generated catalogue appendix is written
  like 2a's (`docs/superpowers/specs/…-pack-issue-catalogue.md`).

## 5. The pipeline

Stages run in order. Stage 1 errors stop everything (no `Pack` exists). Stage 2 errors stop stages 3 to 7 (they need resolved
references). Stages 3, 4 and 5 run together after 2. Stages 6 and 7 run only when stages 2 and 5 are clean. The result is one sorted
list; the loader never raises on content.

| Stage | Checks | Codes |
|---|---|---|
| 1 Schema | TOML parses, types and required fields, unknown keys | `TOML_SYNTAX`, `UNKNOWN_KEY`, `WRONG_TYPE`, `MISSING_FIELD` |
| 2 Closed references | every key named elsewhere exists: location, record, trace kinds, methods, motive types, roles, slot keys; no duplicate keys | `UNKNOWN_LOCATION_KIND`, `UNKNOWN_RECORD_KIND`, `UNKNOWN_TRACE_KIND`, `UNKNOWN_METHOD`, `UNKNOWN_MOTIVE_TYPE`, `UNKNOWN_ROLE`, `UNKNOWN_SLOT`, `DUPLICATE_KEY` |
| 3 Templates | placeholders in the fixed set (`{who}`, `{who.subj}`, `{who.poss}`, `{item.a}`, `{item.the}`, `{place.in}`, `{time.phrase}`; leading `^` capitalises); cross product or a capped sample renders without a stray `{`, doubled word, double space, "a" before a vowel or capital mid-sentence; variants per family at least 5 (7 for long); `claim_slots` appear in every variant | `UNKNOWN_PLACEHOLDER`, `UNRESOLVED_BRACE`, `DOUBLED_WORD`, `DOUBLE_SPACE`, `ARTICLE_MISMATCH`, `MID_SENTENCE_CAPITAL`, `TOO_FEW_VARIANTS`, `CLAIM_SLOT_MISSING` |
| 4 Hygiene and leak | a candidate's distinctive tokens appear only in its own entries across all pack text; trace templates per method equal in count and within ±20% length; every distinctive label token appears in the display name | `LABEL_TOKEN_LEAK`, `TRACE_COUNT_SKEW`, `TRACE_LENGTH_SKEW`, `DISPLAY_NAME_MISSING_TOKEN`, `SECRET_REUSES_LABEL` |
| 5 Plausibility | every role has at least 1 record kind and 3 motive types; every motive type is allowed by some role; every scene type has a legal crime location kind; every method allowed in at least 2 scene types; every wrong method possible at the chosen scene; `slots` enough for the co-location rule and `slot_defs` at least `slots` | `ROLE_NO_RECORD_KIND`, `ROLE_NO_SUSPECT_RECORD` (added during the castle: a suspect's secret is a record about that suspect, so every role needs a record kind whose subject is `suspect`), `ROLE_TOO_FEW_MOTIVES`, `MOTIVE_UNREACHABLE`, `SCENE_NO_CRIME_LOCATION`, `METHOD_TOO_RARE`, `SCENE_METHOD_IMPOSSIBLE`, `SLOT_DEFS_TOO_FEW` |
| 6 Capacity and presets | capacity and `slots` reach every minimum of each preset in `Pack.presets` (reuses `derive_spec`, whose message names every shortfall); effective profiles monotone short ≤ standard ≤ long | `PRESET_UNSUPPORTED`, `PRESET_NOT_MONOTONE` |
| 7 Motive matching | Hall check: a perfect suspect-to-motive matching exists for every roster the pack can produce; max marginal P(motive given role) ≤ 0.5 | `NO_PERFECT_MATCHING`, `MOTIVE_TOO_PREDICTABLE` |

> Plan deviation 2: `UNKNOWN_ROLE`, `UNKNOWN_SLOT` and `DISPLAY_NAME_MISSING_TOKEN` were dropped (no reference site, or deferred to 2d); `ROLE_NO_SUSPECT_RECORD` was added. The pack catalogue has 34 codes.

Reuse, never duplicate: stage 3 and 4 use `core.text` (`tokens`, `normalise`); the leak rule reuses `core.labels` (`token_set`, `distinctive`),
the definition the case validator's group 2 uses; stage 6 reuses `model.spec.derive_spec` and the global presets; capacity checks mirror group 11's.

Stage 7 definitions, since spec 4.11 leaves them open. A *roster* is a set of **distinct** roles of size n for each n in the preset
suspect range (a role appears at most once per case; the generator in 2d must respect this, and the case validator does not enforce it
today). The Hall check runs per roster by augmenting-path matching over each role's `motive_types`. For every roster and role,
P(motive | role) is the share of that roster's valid matchings that give the role that motive (uniform over matchings, which is how
spec 4.11 samples); the bound applies to the maximum over rosters, roles and motives. Matchings are enumerated, at most 7! = 5,040 per
roster, and the castle has at most a few hundred rosters (subsets of 8 roles), so the check is exact and deterministic with no sampling.

## 6. Case-side rules (group 11 additions)

All need a `Pack` (so they are skipped, with the existing `PACK_RULES_SKIPPED`, when `pack=None`), all added to the case
catalogue with `requires_pack`, each with a mutation test and an exact cascade:

- `LOCATION_KIND_NOT_IN_PACK`: a `Location.kind` that is not a pack location kind.
- `LOCATION_KIND_NOT_IN_SCENE`: the crime location's kind is not in the scene type's `location_kinds`.
- `TRACE_KIND_NOT_ALLOWED`: a trace fact's `trace_kind` (section 3) is not in the scene type's `allowed_trace_kinds`, or its location's
  kind is not among the trace's allowed location kinds.
- `RECORD_KIND_NOT_IN_PACK`: a `Claim.record_kind` or record source kind that the pack does not declare.
- `CLAIM_SUBJECT_MISMATCH`: a `record_ref` claim's subject type does not match the pack record kind's `subject`.

## 7. The castle pack

`src/gumshoe/cases/packs/castle.toml`, per spec 4.12 and 4.13: great hall, chapel, keep (and the other location kinds needed to reach
6); visitor ledger and gate log (plus a third kind to reach 3); steward, priest, cook (and the other roles needed to reach 8).
Target counts: 10 names, 8 roles, 6 location kinds, 3 record kinds, 6 motive types, 6 methods with trace kinds and trace templates,
about 12 template families at 5 or more variants, and slot phrases. Capacity: 8 suspects, 7 locations, 6 methods, 3 record kinds.

Authoring process: Claude writes it in chunks (names and roles; locations and records; methods and traces; motives; template families),
the user reviews each chunk, and the pack's own checks must pass before the next chunk begins. The castle never relies on a rule being
lenient: no `warning` suppressions, no skipped stage.

## 8. Testing

Test-first, code review after each task, no live Jev.
- A small valid `Pack` built in Python (`tests/packs/fixtures.py`), the base for mutation tests; one mutation test per code, exact
  cascade, in the style of 2a's `tests/cases/validate`.
- Golden tests for loader messages (key path and suggestion text) and for the generated pack-issue catalogue.
- A never-raises property test: random byte and key mutations of the castle TOML always yield issues or a valid pack, never an exception.
- Skeleton-hash tests: wording change keeps the hash, structural change changes it; cross-process determinism over hash seeds.
- Castle: loads clean; targeted tests for leak tokens, trace balance and the matching bound.
- Architecture test: `packs` imports only core, model, rules; no `validate` import.
- Group 11 additions: mutation tests on the 2a fixture with a pack that declares the kinds.

## 9. Delivery order (becomes the plan's tasks)

1. Architecture rule and richer `Pack` model plus skeleton hash (and `Fact.trace_kind`, with golden regeneration)
2. `PackIssue`, pack catalogue and runner skeleton
3. TOML loader, schema stage, key-path messages and did-you-mean
4. Closed references (stage 2)
5. Template rendering lints (stage 3)
6. Label hygiene and leak rules (stage 4)
7. Plausibility (stage 5)
8. Capacity, presets and monotonicity (stage 6)
9. Motive matching (stage 7)
10. Group 11 case-side rules and their mutation tests
11. `packs check` CLI and the generated pack catalogue
12. Castle content, in reviewed chunks

## 10. Risks and open points

- **Pack TOML shape for new tables is mine.** Spec 4.13 shows only a skeleton; method tables, trace structure and template-family tables
  are designed here and may need adjusting when 2d consumes them. Mitigation: 2d may bump `skeleton_rev` of the castle before any seed is
  published, and no seeds exist yet.
- **Castle prose volume.** About 250 items is review-heavy; chunking limits the cost of a rewrite.
- **Leak rule strength.** Stage 4's token rule could flag natural castle prose (for example "poison" in a cellar description). The
  expected fix is rewording the prose, not weakening the rule; if the rule proves too strict, that is a spec change to discuss, not a
  silent relaxation.
- **`Fact.trace_kind`** (section 3) is the one change to the case schema; it has an explicit fallback.

## 11. Changes made during execution, and items handed to 2d

Added to 2c while authoring the castle (each reviewed and committed):
- `ROLE_NO_SUSPECT_RECORD` (stage 5): a suspect's secret is a record about that suspect, so every role needs a record kind whose subject is `suspect`.
- Scene capacity (stage 6, reported as `PRESET_UNSUPPORTED`): at least 3 scene types must allow each claimed preset's method count. The review of the castle found `long` could only ever happen in the Keep.
- `Fact.trace_kind` and the case-side rules of section 6 (as specified).

Added by the final review of the branch (committed, see the git log of feat/pack-format-2c):
- **Stage 7 work budget.** Exact enumeration is kept, guarded by `MATCHING_BUDGET = 5,000,000`: for each hosted preset the upper bound `C(roles, n) x P(motive types, n)` is computed first, and a preset over budget is reported `PRESET_UNSUPPORTED` ("matching check too large") and skipped by stage 7. Measured: the castle needs about 0.7M (0.05 s); the worst pack the budget accepts (10 roles x 8 motive types, every role allowing every motive) takes about 5.6 s. If packs outgrow it, replace enumeration by a bitmask DP. `NO_PERFECT_MATCHING` is capped at 5 issues per suspect count.
- **Stage 1 stops everything**, including a top-level `UNKNOWN_KEY` (no `Pack` is built). Unknown keys inside `[meta]` are reported as `meta.<key>`; a non-table `meta` is `WRONG_TYPE`.
- **Stage 3 also lints the pack's own pool values** (slot phrases, article + name, traits, labels and aliases) and renders templates with a pool-derived sample.
- **Stage 2 reports a preset claimed twice** (`DUPLICATE_KEY meta.presets[x]`).
- **New case code `RECORD_SUBJECT_MISMATCH`** (group 11): a record source whose subject type differs from the pack's subject for that record kind.
- **`load_builtin_pack(name)` accepts only identifiers.** On a case-insensitive file system `"Castle"` still resolves.

Handed to the 2d generator and its spec (found by the independent castle reviews; none can be fixed inside the pack format as it stands):
1. **Per-method absent templates and per-motive rule-out templates.** The pack has only method-agnostic `trace_inspection` and `absent_trace` families, so a how or why rule-out cannot name its candidate. Parent spec 4.13 had `absent` per trace and `ruleout` per motive; the 2c model dropped both. Add them back before the generator builds how/why rule-outs.
2. **Record names must come from one pool.** Lies are drawn from `lie_record` (book names such as "day book", "tally") while real record facts could be rendered from `record_defs.*.presence` ("visitor ledger", "gate log", "chapel register"). If the two use different name sets, a declared record name always means truth. The generator must draw both from the same pool, or `lie_record` must use the declared names.
3. **Which location kinds a record kind may be about.** A pack does not say that a gate log is about the gatehouse only, so "the gate log shows X in the Kitchen" is possible. Add a per-record-kind `location_kinds` list.
4. **The accused in a framing lie.** In `lie_accusation` the placeholder `{who}` is the person accused (the lie's actor); the speaker comes from the fact's source. The generator's claim-fidelity lint (4.9) must check the accused, not the speaker.
5. **Grammar of "they".** The pack no longer uses the `they` pronoun, but `Entry.pronoun` allows it. Plural verb agreement ("they were") belongs to the generator before any pack uses it.
6. **Distinct roles per roster.** Stage 7 assumes a roster is a set of distinct roles; the case validator does not enforce it today and the generator must respect it.
7. **Proof and rule-out vocabulary.** The pair `trace_inspection` / `absent_trace` shares sentence shape but still carries polarity in word choice ("muddy and scuffed" vs "swept and tidy"). The reviewer judged this acceptable; the 4.5 corpus test in 2d decides.
8. **Witness manner phrases.** Kept at the user's request, moved from the suspect to the witness and written as neutral activities; the same style appears in the lie families so it is not a truth cue. Revisit with the corpus test.
9. **Lint limits worth a follow-up:** `a/an` is first-letter based (flags "an hour"), `doubled_word` fires across sentence boundaries, `mid_sentence_capital` flags "I'm"; the leak scan strips braces in non-template texts such as traits.
