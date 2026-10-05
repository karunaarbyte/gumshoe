# Pack inputs for the evidence, and the castle's wording (2c.1b): design

Status: design, written 2026-10-05 and revised after one independent adversarial review (section 11).
Extends `2026-10-02-pack-format-2c-design.md` (the pack format, its loader and its stages) and answers the survey of
`2026-10-05-generator-assembly-2d3a-design.md` section 10 (what the skin stage will need), which refines `2026-10-05-generator-evidence-2d2-design.md`
section 10. Parent: `2026-10-01-case-engine-design.md` section 4 (themes, templates, leak rules). The generator that consumes this (2d-3b: the
template skin and `skin_lint`) is **not** part of this work: 2c.1b ends when the castle *can* render every fact, not when anything renders it.

## 1. Intent

The generator now builds valid, solvable cases whose text is blank. The castle pack holds wording for a smaller evidence design than the one the
generator builds: it has no text for the culprit's physical proof or an opportunity suspect's physical clearing, for a key, for a neutral
location-record entry, for a lie's contradiction, for a motive's hint, for a method's absence or supporting clue, and no victim, `intro`,
persona style or small-talk vocabulary. Without them the skin stage cannot be written, because it would have nothing to render. 2c.1b adds:

1. the **pack fields and families** that hold that wording (model, loader, `skeleton_view`), all optional in the model so that `Pack` values
   built elsewhere (the case tests' fixtures) are unchanged;
2. a new **check stage** (stage 8, "skin inputs") that refuses a pack that cannot render every fact, with plain codes and key paths, and the
   structural parity rules (equal counts, similar lengths) that keep a text from telling truth from lie. **It is written and tested first and
   wired into the pack load last** (section 5), because a required check on content that does not exist yet would make the castle unloadable;
3. the **castle's content**, about 140 short texts, written in four chunks that the user reviews one at a time;
4. castle **tone tests** (the house rules the castle already follows, extended to the new texts) and the usual mutation tests per new code.

Success criteria:
1. `python -m gumshoe.cases packs check castle.toml` exits 0 with no issue after every commit, and a gap test (section 5) lists, by code and key
   path, exactly what stage 8 would still report, shrinking chunk by chunk to nothing (so the content cannot be forgotten).
2. Every fact kind the generator builds has a text source in the castle (the table of section 3), with at least the counts of section 3, and the
   tone tests pass on every new text.
3. Nothing in the new texts names a method or motive outside its owner (the stage 4 leak rule covers them), a proof and its mirror differ only in
   polarity of words (same count, similar length, same nouns), and no text states a certainty or a negation.
4. The skeleton hash does not change with any wording edit and changes only when a family (id, kind, claim slots) is added or removed.
5. All existing tests keep passing at every commit (those that must change at the wiring commit are listed in section 5); ruff and strict mypy
   stay clean.

Out of scope: the skin stage and `skin_lint` (2d-3b); tuning the small-talk vocabulary (section 9); the other three packs (2e); any change to the
case model, the generator or the validator.

## 2. What the castle has and lacks

Has (`castle.toml`): 12 families (`alibi`, `lie_alibi`, `witness_sighting`, `witness_hearing`, `presence_record`, `lie_record`, `lie_accusation`,
`secret_discovery`, `trace_inspection`, `absent_trace`, `motive_clue`, `small_clue`), per-method trace templates (two per method), per-motive
`secrets` (two per motive), location descriptions and names, record presence lines and display names, role names, nouns and traits, slot phrases.
Of the families, only `presence_record`, `lie_alibi`, `lie_record` and `lie_accusation` are used by facts the generator builds today; `alibi`,
`witness_sighting` and `witness_hearing` have no fact (every presence and alibi fact sits on a record source), and once the owned texts below
exist the generic `secret_discovery`, `trace_inspection`, `absent_trace`, `motive_clue` and `small_clue` are unused as well (8 of the 12). They
are left as they are (section 9).

Lacks, exactly the survey of 2d-3a section 10 (and one more thing it found): the physical items (two polarities), the key clue, the neutral
location-record entry, the contradiction, the per-motive hint, the per-method absent text and clue text, the victim and `intro`, the persona
style, the small-talk vocabulary. The generic `absent_trace`, `small_clue` and `motive_clue` families cannot do these jobs: an absent trace that
does not say what is absent rules nothing out, and a clue that does not belong to a method supports nothing.

## 3. The text of every fact (the contract with 2d-3b)

A fact's text comes from a source chosen by its **fact kind and source kind**. `n` is the most such facts one case holds (long preset: 7
suspects, 5 methods, 6 locations, 3 opportunity suspects, gating depth 2).

| Fact (neutral id) | Kind, source | Text from | Slots a variant carries | n (long) |
|---|---|---|---|---|
| `sec_k` | SECRET, record | `motive_defs.<motive>.secrets` (exists) | who | 7 |
| `e_k` (all), `w_k` (the 3 neither culprit nor opportunity) | PRESENCE or ALIBI, record | family `presence_record` and the record's `presence` lines (exist; 2d-3b chooses) | who, place.in, time.at, record | 10 |
| `x_k` (the culprit) | PHYSICAL, record | **new** family `physical_proof` | who, record | 1 |
| `x_k` (an opportunity suspect) | PHYSICAL, record | **new** family `physical_clear` | who, record | 3 |
| `y_k` | MOTIVE_CLUE, interrogate | **new** `motive_defs.<motive>.hints` | who | 7 |
| `l_k` | LIE, interrogate | families `lie_alibi`, `lie_record`, `lie_accusation` (exist) | who, place.in, time.at | 7 |
| contradiction of `l_k` | the lie's `Fact.contradiction` | **new** family `contradiction` | who, place.in, time.at, record: see below | 7 |
| `h_mj` (true) | TRACE, search | `method_defs.<m>.traces[].templates` (exist) | place.in | 1 |
| `h_mj` (others) | ABSENT_TRACE, search | **new** `method_defs.<m>.traces[].absent` | place.in | 4 |
| `p_mj` | CLUE, search | **new** `method_defs.<m>.clues` | place.in | 5 |
| `c_k` | CLUE (key), search | **new** family `key` | who | 7 (depth 2, which is always the case on `long`) |
| `n_<kind>` | CLUE, location record | **new** `record_defs.<kind>.entries` | record | 1 per location-record kind (castle: the gate log) |
| the case | `intro` | **new** family `intro` | victim, place.in, time.during | 1 |
| the case | the victim | **new** `Pack.victims` | | 1 |
| each suspect | persona | role `traits` (exist) and **new** `RoleDef.style` | | 7 |
| the case | `smalltalk_allow` | **new** `Pack.smalltalk_allow` (starter list; section 9) | | 1 |

The five new families have **unique kinds and the ids equal to the kinds**: `physical_proof`, `physical_clear`, `key`, `contradiction`, `intro`
(the kind is how 2d-3b finds a family; the existing kinds are not unique, `lie` has three families, which is why new ones are looked up by
these).

Notes on the contract.
- **Why 7 variants, honestly.** The 7 (5 for a pack that claims no `long`) is the existing rule for every family, not a new one. A rendered
  sentence contains `{who}`, so two facts of different suspects never render identically; the real risk is repeating the same *frame* ("{who}
  was ...") for ten presence facts, which 7 frames cannot avoid and which is 2d-3b's to manage. The families without a `{who}` (`intro`,
  `entries`) occur once per case, and owned lists of 3 are enough within a case because each motive and each method appears once; they limit
  cross-case variety only.
- **Owned texts** (a method's `absent` and `clues`, a motive's `hints`) belong to one candidate: the leak rule of stage 4 lets a candidate's own
  distinctive tokens appear in its own entries (as it does for a method's trace templates) and nowhere else. A motive's hints, like its secrets,
  must not reuse its label tokens: the hint evokes the motive and the secret proves it.
- **`absent` pairs with `templates`** per trace kind: the same number of texts, each saying what the trace of that method would have left and is
  not there, naming the place (`place.in`). **`clues`** are method-specific supporting texts that hold no trace (`place.in`).
- **The contradiction** is rendered for a (lie, exposer) pair. The lie already states its own, false, place, so `place.in` here is the **true**
  place, the one the exposer (the suspect's own record fact `e_k`) claims, `time.at` the crime slot and `record` the exposer's record; the lie's
  own place is not available to the text unless a slot is added, and the families do not need it ("But {record} put {who} {place.in} {time.at}").
- **The physical items** are things a household officer *notes in a record about a person* (so each variant carries `{who}` and `{record}`:
  the existing castle test forbids a hard-coded record name), described and never judged, with no place and no time (the scene and the crime slot
  are what the `intro` states). **What each shows:** the culprit's `physical_proof` describes a thing of theirs found marked or out of place
  at the scene (damp, torn, stained); an opportunity suspect's `physical_clear` describes the thing they would have had to use, checked after the
  crime and found unmarked and where it belongs. The first is incriminating because the thing was used, the second exculpating because it was not,
  and a player can derive the rule-out from it (an item "found intact at the scene" would show nothing).
- **Shape parity** (the reason the new families come in pairs and equal counts, section 5): `physical_proof` and `physical_clear` have the same
  number of variants, mean lengths within **10%** and overlapping length ranges, the same nouns, and differ in the polarity of their words only;
  every method has the same number of `absent` texts, of `clues` and of trace templates; every motive the same number of hints; and the mean
  length of all `absent` texts is within 10% of that of all trace templates (the true method's text is always a template, the others' always an
  `absent`: a length gap between the two would name it). A player who can tell a truth from a lie, or the true method from a false one, by the
  length, count or shape of its text has been given the answer. (The culprit is the only suspect with a `physical_proof` and a case shows one to
  three `physical_clear`, so the proof would be the longest of the case's physical items whenever it is a few characters longer on average: a
  mean bound of 20% is not enough, hence 10% and the overlap.)
- **No certainty, no negation words** in a proof or a rule-out (the existing castle tests, `CERTAINTY_WORDS` and `NEGATIONS`, extended to every
  new text): polarity is carried by what is described (damp against dry, marked against clean), never by "not" or "no".
- **The `intro`** states the victim, the scene (`{place.in}`, the scene's location name) and the crime slot (`{time.during}`): the whole
  who-deduction rests on knowing where and when the crime happened, so every variant carries all three. It names neither a method nor a motive
  nor a suspect.
- **The victim is the lord.** The castle's existing secrets and descriptions refer to "the lord" throughout (his chain of office, his will, his
  strongroom, a sister he sent away), so `victims` is a pool of **lord names with their title** (`Lord Aldric`): `{victim}` renders the name
  with the title, `{victim.subj}` and `{victim.poss}` come from the entry's pronoun, which is therefore required (and `proper`).

## 4. Pack model and loader

All new fields are optional with an empty default, so `Pack` values built elsewhere (the case tests' fixtures, hand-built packs) are unchanged:

- `TraceDef.absent: tuple[str, ...] = ()`; `MethodDef.clues: tuple[str, ...] = ()`; `MotiveDef.hints: tuple[str, ...] = ()`;
  `RecordDef.entries: tuple[str, ...] = ()`; `RoleDef.style: str = ""`; `Pack.victims: tuple[Entry, ...] = ()`;
  `Pack.smalltalk_allow: SetTexts = ()`.
- New families are ordinary `FamilyDef`s with the kinds `physical_proof`, `physical_clear`, `key`, `contradiction` and `intro` (ids as the kinds,
  one family each, kinds unique: section 3).
- New placeholders: `victim`, `victim.subj`, `victim.poss`, in `KNOWN_PLACEHOLDERS`, **both** `SAMPLES` (a missing key renders as an empty
  string, silently), `pack_sample` (from the first victim, with the pronoun table it already uses) and the `SAMPLE` dict of `test_castle.py`.
- Loader: `victims` is a list section (`[[victims]]`, like `slot_defs`), `smalltalk_allow` a key of `[meta]` (like `presets`); `absent`, `clues`,
  `hints`, `entries` and `style` sit inside their existing tables. Unknown keys stay refused.
- `skeleton_view`: unchanged except that nothing new is added: the new fields are wording and the new families enter through the existing
  `families` projection (id, kind, claim slots), so adding a family changes the hash and editing a variant does not (the existing design,
  reused: `skin_rev` is not in the view).

## 5. Checks: stage 8 "skin inputs", the stage 3 and 4 extensions, and the rollout

Stage 3 (templates) and stage 4 (hygiene and leaks) learn the new fields:
- `templates.template_items` yields `traces[].absent`, `clues`, `hints` and `entries`; `lint.pool_items` yields `victims` and `style` (which
  feeds the stage 3 pool-text lint).
- `hygiene._texts` (which does **not** use `pool_items`: it lists its own sources) gains `victims` and `style`, so they are leak-scanned, and its
  owner dict gains `traces[kind].absent[i]` and `clues[i]` (owner: the method) and `hints[i]` (owner: the motive), with the same path strings
  `template_items` emits. `SECRET_REUSES_LABEL` covers `hints`; its message is reworded ("an owned text of {candidate}, a secret or a hint,
  reuses its own label token").
- `_role_collisions` also checks every victim name against candidate tokens and against role names and nouns (`ROLE_TOKEN_COLLISION`).

Stage 8 is a module of its own (`check/skin_inputs.py`), run with stages 3, 4 and 5 once stage 2 is clean (it reads resolved references, and a
pack in the middle of being written should see every gap at once), and reports, with a key path:

| Code | Meaning |
|---|---|
| `MISSING_FAMILY` | one of the required family kinds is absent (`physical_proof`, `physical_clear`, `key`, `contradiction`, `intro`) |
| `DUPLICATE_FAMILY_KIND` | two families carry the same required kind |
| `TOO_FEW_TEXTS` | a list is shorter than its minimum: `absent` per trace the number of `templates` of that trace, `clues` 3, `hints` 3, `entries` 3 for a location-record kind, victims 6, small-talk 20 (the minimums are variety, nothing more) |
| `ENTRY_INCOMPLETE` | a victim lacks its pronoun or `proper`, or a role has no `style` |
| `TEXT_COUNT_SKEW` | the count of `absent`, `clues` or `hints` differs between candidates (every method, every motive must have the same) |
| `TEXT_LENGTH_SKEW` | the mean rendered length of a candidate's `absent`, `clues` or `hints` is more than 20% from the mean over candidates; **and** the mean of all `absent` texts is more than 10% from the mean of all trace templates |
| `PAIR_COUNT_SKEW` | `physical_proof` and `physical_clear` have different variant counts |
| `PAIR_LENGTH_SKEW` | their mean rendered lengths differ by more than 10%, or their length ranges do not overlap |
| `BAD_SMALLTALK_WORD` | a small-talk entry is not exactly one word (it must tokenise, by `core.text.tokens`, to exactly one token and be lowercase letters), repeats, or **is a token (stemmed) of any method or motive label or alias, or of a role name or noun** |

The last rule is the one that matters: `reply_check` *subtracts* the stemmed tokens of `smalltalk_allow` from what it flags, so an over-generous
list **hides** a persona mentioning a method or a motive ("wine", "knife", "rope", "faith" would each mask one). The list may hold only words
that are no candidate's token.

Codes are plain names that collide with no case code (the test that enforces this stays; the golden pack-issue catalogue is regenerated).
The `TOO_FEW_VARIANTS` rule of stage 3 already applies to the new families (7 variants when the pack claims `long`).

**Rollout: content first, wiring last.** A required check on content that does not exist makes the castle unloadable (`load_builtin_pack`
refuses any error), which would break `tests/generate` (through `tests/generate/helpers.castle()`), `tests/cases/tools` and every castle test.
So: the stage 8 module and its codes land first and are **not** called by `check_pack`; a castle **gap test** calls the module and asserts the
exact set of codes and paths it would report, which each chunk shrinks until it is empty; after C4 the last commit wires stage 8 into
`check_pack` and `load_pack`. Tests that change at the wiring commit: `test_catalogue` (stages one to *eight*), the runner and pipeline tests of
`test_pipeline.py` (the stage lists and call order), `test_pack_cli` and the base-clean tests (the base pack is the `BASE_TOML` text of
`tests/packs/fixtures.py`, not `build_pack`: it gains minimal valid content for every new field, about 100 lines, and every mutation edit must
stay unique against the longer text), and the mutation harness: until the wiring commit the stage 8 mutations call the module directly, at the
wiring commit they move to the load pipeline and `test_every_pack_code_has_a_mutation` covers the new codes.

The **castle tone tests** (`tests/packs/test_castle.py`, where the existing ones live) are extended, not weakened: no certainty or negation word in
any new proof, rule-out, clue, hint or physical text; the two physical families use the same nouns, audiences and shape; traces, absences and
clues describe objects, never bodies; hints carry no place or time (as secrets); no two variants of a family render the same sentence; no
hard-coded record name; `intro` variants carry victim, place and time; `entries` are neutral (no suspect, no method, no motive). These are
**tests, not pack checks**, because they are judgements about this pack's prose; the pack checks are the structural parity every pack must meet.
(So the same-nouns and polarity-only rules protect the castle only: the other three packs of 2e get the structural checks and need these tests
written for them, or promoted to checks then.)

## 6. The castle content

Volumes (castle: 8 roles, 8 motives, 6 methods with one trace each, 7 location kinds, 3 record kinds of which one is about a location):

| Chunk | Content | Items |
|---|---|---|
| **C1** families | `physical_proof` 7, `physical_clear` 7, `key_clue` 7, `contradiction` 7, `intro` 7 | 35 |
| **C2** methods | `absent` 2 per trace (6 traces) = 12; `clues` 3 per method (6 methods) = 18 | 30 |
| **C3** motives | `hints` 3 per motive (8 motives) | 24 |
| **C4** the rest | `entries` 3 (the gate log), role `style` 8, `victims` 6 to 8 lords, starter `smalltalk_allow` about 30 | about 50 |

Process (as in 2c): the pack's checks and the tone tests must pass before a chunk is shown; the user reads each chunk and may rewrite it; the next
starts after approval; `skin_rev` is bumped once, with the first chunk (wording only: the skeleton hash is unaffected). Each chunk lands as one
commit that touches `castle.toml` and the castle tests.

**Voice** (what the existing 12 families already do, and the new texts follow): plain, concrete, past tense, one sentence, no adverbs of
certainty, objects and habits instead of feelings, no proper nouns other than placeholders, ordinary words a 12-year-old knows. A text names a
thing a player could picture and never says what it means.

## 7. Versions and hashes

`skin_rev` goes to 2 with C1. `skeleton_rev` stays 1; the castle skeleton hash changes once, when C1 adds the five families (the families
projection holds id, kind and claim slots), and not for any later wording; the golden snapshot of the 2d stage digests does not move (it does
not depend on the pack's families), and the case digests (`skeleton_digest`) do not contain the pack reference. The `PackRef.skeleton_hash` of
generated cases changes, which only the tests that compare it to `pack.skeleton_hash()` see. Two more consequences, both harmless while nothing is
published and accepted here: every generated `Case.id` changes (the id hashes the pack's skeleton hash), and `regenerate` raises
`VersionMismatch` for a case stored before C1. Per-chunk wording edits do not bump `skin_rev` (it moves once, with C1).

## 8. Testing

- **Model and loader:** each new field round-trips through `load_pack`; an unknown key inside the new tables is refused with a key path; a wrong
  type in `victims` or `smalltalk_allow` is a `WRONG_TYPE`.
- **Stage 3 and 4 extensions:** one mutation per new place a text can go wrong (a doubled word in an `absent` text, a method token in another
  method's `clues`, a motive label token in a `hint`, a victim named like a role).
- **Stage 8:** one mutation test per code with the exact cascade (as the 2c codes have; calling the module directly until the wiring commit, the
  load pipeline after), the generated pack-issue catalogue regenerated and its golden test updated, the `BASE_TOML` of `tests/packs/fixtures.py`
  extended at the wiring commit (section 5), the castle gap test.
- **Castle:** loads clean after every chunk; the tone tests of section 5; every method has the same number of `absent` texts as trace templates;
  every candidate's counts and lengths match (they are also stage 8 checks; the `secrets` are not compared, the castle has two each); the hash tests of section 7 (a wording edit keeps the hash, removing a
  family changes it); a **render smoke test**: every new text renders with the SAMPLES and the pack sample to a sentence without a stray brace.
- Every new test is shown able to fail (the usual "prove it can fail" step).

## 9. Deferred and open

- **The small-talk vocabulary is a starter list.** The parent spec (5.6) says it is "tuned on a corpus of persona replies at pack-authoring time":
  the corpus needs the persona agent (sub-project 4). 2c.1b writes a conservative list of everyday words (greetings, meals, weather, the household)
  and the format check, and says so in the pack; tuning waits for the agent loop. `reply_check` uses it only to subtract allowed tokens from
  what it flags, so an *incomplete* list produces extra violations and an *over-generous* one hides leaks, hence the `BAD_SMALLTALK_WORD` rule
  (section 5): the starter list contains no token of any candidate.
- **Which of `presence_record` and the record's own `presence` lines renders a presence fact** is 2d-3b's choice; both are kept.
- **Locations of the generic families** (`small_clue`, `motive_clue`, `absent_trace`, `trace_inspection`) stay in the pack: the new owned texts
  replace their jobs in the generated cases, and the tone tests that cover them keep covering them. Whether to delete them is 2d-3b's call, once it
  knows what it uses.

## 10. Decisions for the user, and risks

Decisions the author made and the user may overturn (each is cheap to change before C1 is written):
1. **The physical item is a noted object** (section 3): described in a record entry about the person, found at the scene, culprit damaged and the
   cleared suspect's intact. The alternative (a physical item found by searching a place) would put `x_k` on a search source, which the evidence
   design does not do (the who-evidence is in the suspect's record).
2. **The victim is the lord, named**, from a pool of lord names with their title (`victims`, with a pronoun): the castle's existing text already
   says "the lord", the intro reads better with a name, and the name is skin only (no skeleton hash, no validator rule).
3. **Two physical families, not a template with a polarity flag**: the pair is visible in the pack and checked for parity as a pair.
4. **Counts**: 7 variants per shared family (the existing rule), 3 per owned list, 2 `absent` per trace, a 10% length bound for the pairs that a
   player could compare. More texts are welcome, fewer are refused.
5. **Tone tests, not checks, for prose judgements** (section 5).

Risks:
- **Volume and voice.** About 140 texts: review-heavy; the chunking limits a rewrite to one chunk, and the voice paragraph above is the thing to
  correct first if the first chunk reads wrong.
- **Leak rule strength** (as in 2c): a natural castle sentence may use a candidate's token ("candle" in a hall description). The fix is rewording,
  never loosening the rule.
- **The contract table is the design of 2d-3b in advance.** If 2d-3b needs a different split (one family per fact kind and source, say), the cost
  is renaming kinds in the pack; the texts are reusable.
- **New required content makes every pack fail stage 8 until it is written**, which is why stage 8 is wired in last (section 5). The castle is the
  only pack; the other three (2e) are written against this contract.
- **The parity bounds are tuned by argument, not by a corpus** (10% and overlapping ranges for the physical pair and for `absent` against
  templates, 20% between candidates): they remove the obvious length tells; the 2d-4 statistics (text length against truth) are the real test.

## 11. Review

One independent adversarial review (it read the spec, the pack layer, the castle and its tests, ran the pack suite, and recounted the
generator's facts). One blocker and a set of should-fix findings; none challenged the contract table's coverage ("the facts stage emits exactly
the kinds in the table; there is no missing kind"), the counts, the hash claims or the decision not to touch the case model, the generator or
the validator.

| Finding | Disposition |
|---|---|
| **Blocker:** a required stage 8 makes the castle unloadable until all content exists (breaking `tests/generate`, `tests/cases/tools`, the castle tests), contradicting the criteria; "all fields optional" does not protect existing tests once a check reads them | rollout reordered: module and codes first, not wired; a gap test; wired last; the tests that change at the wiring commit are listed (sections 1, 5) |
| the named victim conflicts with the castle's "the lord" text | the victim is the lord, from a pool of lord names with titles; pronoun and `proper` required (section 3, `ENTRY_INCOMPLETE`) |
| physical texts need `{record}` (the castle forbids hard-coded record names) and `physical_clear`'s meaning was undefined | slots `who, record`; what each item shows is defined (section 3) |
| a 20% mean bound lets the culprit's proof be the longest item in most cases; nothing tied the true method's text (a template) to the others' (`absent`) | 10% and overlapping ranges for the pair; `absent` against templates pack-wide (sections 3, 5); same-noun rules are castle tests only, said so |
| an over-generous `smalltalk_allow` hides leaks (`reply_check` subtracts it) | `BAD_SMALLTALK_WORD` rejects any candidate or role token, stemmed (section 5); the claim corrected (section 9) |
| the contradiction slot's place was unspecified | the true place, the exposer's (section 3) |
| the leak-scan extension named the wrong function | `hygiene._texts` and its owner dict, `SECRET_REUSES_LABEL` reworded (section 5) |
| table errors: presence count n=10 not 14; the dedupe rationale did not hold; the 7 variants are an existing rule | corrected (section 3) |
| §2 undercounted the unused families; `key_clue` against kind `key`; kinds are not unique; no duplicate-kind handling | corrected; ids equal kinds; `DUPLICATE_FAMILY_KIND` (sections 2, 3, 5) |
| generated case ids change and `regenerate` refuses old cases when C1 lands | recorded as accepted (section 7) |
| nits: `secrets` parity claim unenforced; `victim*` sample keys; the `skin_rev` rule per chunk; minimum counts arbitrary | claim dropped; keys listed (section 4); rule stated (section 7); minimums said to be variety only (section 5) |

The revisions were not reviewed a second time.
