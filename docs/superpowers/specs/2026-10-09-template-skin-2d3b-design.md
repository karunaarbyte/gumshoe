# Template skin and `skin_lint` (2d-3b): design

Extends `2026-10-03-generator-2d-overview-design.md` (2.3 retry, 2.4 skeleton versus skin, 2.5 ownership), `2026-10-05-generator-assembly-2d3a-design.md`
(sections 6, 10, 11) and `2026-10-05-castle-evidence-wording-2c1b-design.md` (section 3, the contract this spec renders). Parent rules: case-engine
design 4.2, 4.5, 4.6, 4.7, 4.9. Status: draft for user review (2026-10-09).

## 1. Intent

`generate(seed, preset, castle)` returns a valid, solvable case whose every text field is filled from the castle's templates: no LLM, no blanks.
Success means: (1) every fact, contradiction, `intro`, victim, persona field and description reads as a sentence; (2) the skeleton is untouched, so
`validate` reports the same codes before and after skin; (3) no text tells truth from lie, or the true method or motive from a false one, by a
token, a count, a length or a frame; (4) the same seed and pack give a byte-identical case; (5) a developer can read a whole case from the CLI.

User decisions (2026-10-09): the case id stays **skeleton-only** (a wording-only pack edit changes `skin_hash` and the text, never the id);
`skin_lint` ships the **full set** now (leak lint, label against display name, dedupe, claim fidelity), so the later paraphrase pass (parent 4.9)
reuses it; the text of a fact comes from a **fixed mapping in code** (fact kind and source to family), variants dealt per family.

Out of scope: LLM paraphrase, statistics and the digest pin (2d-4), deleting the unused generic families, tuning `smalltalk_allow` (waits for the
persona agent), MCP, agent loop, UI.

## 2. Facts found while grounding the design

These corrected the first outline and are binding:

1. **Skin sees final ids, not neutral ones.** The skin stage receives the assembled case (`skin(ctx, stream, case)` in `pipeline.py`), whose ids are
   hashes. The prefixes `sec, e, x, w, y, l, h, p, c, n` are gone, so a fact's role is read from its **structure**: `kind`, `source`, `effects`,
   `claim`, `truthful`, `trace_kind`, and the case's `truth`. Variants are dealt in **final-id order** (pseudo-random per case; this was the open point
   of 2d-3a section 11). The property "adjacent facts do not repeat a frame" comes from dealing a shuffled list without replacement, not from the order.
2. **Family choice follows meaning; variant choice does not.** Parent 4.7 says skin never depends on effect kind. Choosing `physical_proof` against
   `physical_clear` needs the WHO effect (PROVES against RULES_OUT), so the rule is amended: the **family** may depend on kind and effect (it is what
   the fact means); the **variant**, its order and the stream never do.
3. **There is no "touching" function in the gate.** Parent 4.5 says to reuse it; `rules/gate.py` has `lead`, `held_rule_out`, `permission`, not a
   touching set. This spec defines it: a fact **touches** candidate C (a method or motive) when one of its `effects` names C. It lives in `skin_lint.py`.
4. **A lie is always spoken by its actor.** The facts stage builds `l_k` with `speaker == claim.actor` (interrogate source, `exposed_by` the
   suspect's own record fact). The three lie families (`lie_alibi`, `lie_record`, `lie_accusation`) are therefore **pooled** for lies, and
   `{who}` is the actor in all three. "The accused in a framing lie" (2c spec 190) is the actor for this generator; claim fidelity checks
   `claim.actor`, and a test mutates a lie so that `speaker != actor` to prove the check follows the actor, not the speaker.

## 3. The skin stage (`generate/skin.py`)

`skin(ctx, stream, case) -> Case` replaces `identity_skin` as the default in `run_pipeline`. It returns `case.model_copy(update=...)` with skin
fields only. `STAGE_VERSIONS["skin"]` goes 1 to 2; `SKELETON_ALGO_VERSION` stays 2 (no skeleton output changes).

**Fact roles, read from structure** (the mapping table is one constant in `skin.py`, tested against the 2c.1b contract table):

| Role | Detected by | Family or list | Slots |
|---|---|---|---|
| secret | kind SECRET | the suspect's motive `secrets` | who |
| presence or alibi | kind PRESENCE or ALIBI, record source | `presence_record` | who, place.in, time.at, record |
| physical proof | kind PHYSICAL, WHO PROVES | `physical_proof` | who, record |
| physical rule-out | kind PHYSICAL, WHO RULES_OUT | `physical_clear` | who, record |
| motive hint | kind MOTIVE_CLUE | the motive's `hints` | who |
| lie | kind LIE | pooled `lie_alibi`, `lie_record`, `lie_accusation` | who, place.in, time.at (record from `exposure_hook`) |
| true trace | kind TRACE | the method's `traces[trace_kind].templates` | place.in |
| absent trace | kind ABSENT_TRACE | the method's `traces[trace_kind].absent` | place.in |
| method clue | kind CLUE, search source, HOW SUPPORTS | the method's `clues` | place.in |
| key | kind CLUE, search source, no effects | family `key` | who |
| location entry | kind CLUE, record source on a location | the record kind's `entries` | record |

The suspect (`who`), place and record come from `claim`, `source`, `exposure_hook` and the roster, as the 2c.1b table lists. Anything the table
cannot place raises `GenerationError` ("the skin has no text for fact X"), which the run turns into a failed attempt; the castle never does.

**Other fields.** `Fact.contradiction` of a lie: family `contradiction`, rendered with the true place and the crime slot of the exposer's record
fact (2c.1b section 3). `intro`: family `intro` with the victim, the scene location and `time.during` of the crime slot. Victim: the first of
`Pack.victims` by rendezvous `rank` on the case stream (name with title, pronoun for `{victim.subj}` and `{victim.poss}`). Suspect: `display_name`
(the roster's name), `description` (role noun line from the pack), `traits` (a fixed number drawn by `rank` from the role's traits), `style` (the
role's `style`), `secret_text` (the rendered secret fact). Location: `name` and `description` by `rank` from the kind's `names` and `descriptions`,
distinct within a case. Method and motive labels are skeleton and stay. `smalltalk_allow` is copied from `Pack.smalltalk_allow`.

**Dealing.** For each family or owned list the variants are shuffled once on `stream.child("deal/<family>")` and dealt in final-id order of the
facts that use it; a list shorter than its uses wraps (and `skin_lint` dedupe reports an identical sentence). Each fact's remaining draws (trait
choice and the like) use `stream.child("fact/<final id>")`. Both children hang off the stage stream (`ctx.stream("skin", n["skin"])`), so a skin
retry moves everything and a new fact does not reshuffle others.

**Rendering** reuses `packs/check/lint.render` and the slot tables (`phrase`, pronoun rules): the case supplies the values, the pack the words.

**Bookkeeping** (`pipeline._stamp`): `skin_rev = pack.skin_rev`, `pack_versions` gains `("skin_rev", pack.skin_rev)`, `skin_hash` is the existing
`skin_hash(case)`. The case id is unchanged in form: it hashes the skeleton hash, seed, preset, spec, `SKELETON_ALGO_VERSION` and
`generator_version()`; `skin=2` in `generator_version()` renames every case once, which is fine before the 2d-4 pin.

## 4. `skin_lint` (`generate/skin_lint.py`)

`lint(case, pack) -> tuple[SkinIssue, ...]` is pure. Codes are plain names in a catalogue (`generate/skin_catalogue.py`, same style as the pack
catalogue), each with `fix_stage = skin` and a message template; a test checks that no code collides with a case or pack code.

| Code | Rule |
|---|---|
| `LEAK_TOKEN` | a distinctive token of method or motive C (`core.labels.distinctive` over `token_set` of label and aliases, minus tokens shared with other candidates) appears, stemmed, in the text of a fact that does not touch C (section 2.3). Suspect names are exempt. |
| `MENTION_EXTREME` | the truth's total mention count of its own tokens, over the case's texts, is the unique maximum or minimum among the candidates of its axis (parent 4.5 warning, an issue here so the retry sees it) |
| `LABEL_NOT_IN_NAME` | a distinctive token of a suspect's label is missing from `display_name` (4.6) |
| `DUPLICATE_SENTENCE` | two facts, or a fact and a contradiction, render to the same normalised text (4.2) |
| `CLAIM_VALUE_MISSING` | a fact's text lacks its rendered claim value: the actor's name, the place phrase, the slot phrase (4.9); for a lie the actor, never the speaker |
| `CONTRADICTION_MISSING` | a lie has no `contradiction` text or it lacks the true place |
| `BLANK_TEXT` | a skin field of an entity that needs one is empty (fact text, name, description, `intro`) |
| `BAD_RENDER` | a stray brace, doubled word, double space or `a`/`an` mismatch in a rendered text (stage 3 rules, applied to the case) |

An issue holds `code`, `path` (for example `facts.<id>.text`) and the fill-in parameters. `lint` never reads the validator.

**Run order per attempt:** skin, then the strict validator (unchanged; it must report nothing new, which keeps the skeleton equality honest on every
case), then `skin_lint`. A `skin_lint` call is one attempt against the budget of 20. Any `SkinIssue` is an error and maps to `fix_stage = skin`,
so `Retry.fail("skin")` bumps `n[skin]` and the next attempt uses a new stream; after 5 skin retries the controller escalates one stage back, as
for every stage. `Attempt.codes` records the lint codes, which is the data for the worked retry table the overview asks for. The default lint is
injectable like `validator` and `skin` for tests.

## 5. API and CLI

`generate()` returns the skinned case (the skeleton-only builder stays internal for the 2d-2 tests). The `generate` command gains a readable
rendering: the intro, the suspects with their persona fields, then the facts grouped by source (location search, suspect questioning, record), each
with its text and, in a `--debug` form, its role and effects. This is how the user reads a real case.

## 6. Testing

Every test is shown able to fail (mutation proof with `PYTHONDONTWRITEBYTECODE=1`).
- **Rendering:** each role of section 3 renders from its family or list (test per row, built on a generated castle case); no skin field of a
  generated case is blank; dealing wraps; a case with a missing list raises `GenerationError`.
- **Skeleton untouched:** over 3 presets and many seeds, skeleton hash and `validate` codes before and after skin are equal; `validate` of the
  skinned case has zero errors.
- **Lint:** one mutation test per code that produces exactly that code (a planted leak token in a non-touching fact, a duplicate sentence, a lie
  whose text names the speaker, a label token missing from a name, a stray brace, a blank field, a `speaker != actor` lie).
- **Determinism:** same case in-process, across processes and hash seeds; wording-only pack edit keeps id and skeleton hash, changes `skin_hash`;
  `final` golden digests re-pin once (earlier stage digests do not move).
- **Retry:** an injected lint that fails twice, a lint that never passes (budget ends with `CaseGenerationError`), a skin that raises.
- **Corpus statistics** (fixed seeds, `slow` marker, Bonferroni): text length against truth role (physical pair, true trace against absent, true
  motive hint against others), variant index against truth role, mention-count rank of the true method and motive, and the position of `{place.in}`
  in absent texts against templates (the shape tell deferred from 2c.1b).
- **Smoke:** 1,000 cases per preset; mean attempts at most 1.05; zero lint retries expected; failure distribution printed per code.

## 7. Task order (suite green after each)

1. Skin issue model and catalogue, `touching`, token helpers.
2. Lint rules, test first, one rule per commit.
3. Renderer: facts, then contradictions, then intro, victim, persona and locations.
4. Wire into the controller, bump the stage version, stamp `skin_rev`, re-pin `final` goldens.
5. CLI text output and a readable dump of one case per preset (**the user reads it before the work counts as done**).
6. Corpus statistics and smoke.

## 8. Risks and open points

- **Mention extremes and shape tells are unmeasured on real text** until task 6. If a statistic fails, the fix is rewording the pack (a 2c.1b-style
  wording wave), never loosening a rule.
- **Role detection from structure** (section 3) is a second description of what the facts stage built. A test generates all presets and asserts every
  fact maps to exactly one row, so a facts-stage change that adds a shape fails loudly.
- **One lie pool across three families** mixes first-person, record and hearsay frames per case; if the corpus shows frame against truth role, split
  by exposure instead.
- **Deferred minors from 2c.1b** other than the `{place.in}` position stay deferred: `skin_ready` asserts `in` not `count==1`; negation-flavoured
  words outside the list; style/entries not in the hash test.
- **The case id carries the stage versions**, so any later skin algorithm change renames cases; the 2d-4 pin decides when that stops.

## 9. Amendments from the prototype (2026-10-09; they win over sections 3 to 8)

The plan (`docs/superpowers/plans/2026-10-09-template-skin-2d3b.md`) was prototyped and replayed task by task, then reviewed by an independent agent. It changed the spec in eleven places:

1. **One attempt judges the validator and the lint** (section 4): a clean case is still attempt 1, `regenerate` (budget 1) still works. A lint failure consumes the attempt.
2. **A skin that raises asks the validator first**: the validator's codes on the assembled skeleton win; only a sound skeleton gives `STAGE_ERROR` on `skin`.
3. **`MENTION_EXTREME` is a corpus statistic, not a lint code** (it fired on 29% of cases by chance); the "suspect names are exempt" clause is dropped. Seven lint codes remain.
4. **The leak lint uses the pack's distinctive tokens** (`hygiene.candidate_tokens`), not the case's.
5. **Suspect `description` stays blank**; `display_name` is the label.
6. **The golden `final` digest does not move**; a new `skin` key pins the wording. `SKELETON_ALGO_VERSION` stays 2.
7. **No `slow` marker** (statistics run in the suite, about 5 s); the CLI has `--text` only.
8. **A real tell was found, then a stronger one (independent review), and fixed at the source**: the castle's absent texts put the place early (0.16 of the way through against 0.53 for true traces, z = 27), and inside one case the shortest decisive text was the true trace 59% of the time against 26% (z = 26) because absent texts were longer and more often named their method. New stage 8 code `TRACE_SHAPE_SKEW` (each trace's absent texts mirror its templates: same words, commas and method naming, length within one character, place within 0.10) replaces the single pooled position check, all 12 castle absent texts are reworded and `skin_rev` goes 2 to 3. The statistics are in-case attacks (section 6 stands, with these tests).
9. **Skin and lint errors stay inside the controller**: lookups raise `GenerationError`; a lint that raises is a `STAGE_ERROR` on the `skin` stage.
10. **`regenerate` refuses a changed wording** (another `skin_rev`, or the same with another `skin_hash`).
11. **Dropped on purpose**: a suspect gets all of its role's traits; `description` stays blank (a known gap against success criterion 1).
