# Stage 5: pack hardening, pack choice, and two new packs (design)

Status: plan 5a (the hardening checks) is implemented; design approved in conversation 2026-10-26; revised the same day after an independent review that
checked the draft against the code (one blocker, nine important findings, all folded in). Awaiting the
owner's read of this revision. Implements stage 5 of `docs/superpowers/roadmap-after-5.md`. Builds on the
pack format (2c), the generator (2d) and the hardening list in
`2026-10-05-generator-evidence-2d2-design.md` section 10.

## 1. Goal and success criteria

Replayability today depends on one pack (`castle`): seeds only reshuffle its names, places and clues.
Stage 5 adds two settings, an **ocean liner** and a **1920s theatre**, lets the player choose the setting,
and first makes the pack checks strict enough that a bad pack is refused at load, not halfway through
generating a case.

Done when:
- every hardening item of section 4 is a pack check with a mutation row, and the golden catalogue is updated;
- the castle loads with no new errors, `tests/generate/golden/castle_stages.json` regenerates with no diff,
  and a committed pre-stage-5 castle save still loads (section 5, "Saves");
- the API and title screen offer the three settings and the choice is saved with the game;
- each new pack loads with zero errors, `smoke` is green on every claimed preset, the setting-neutral quality
  and symmetry tests pass on it, and a reviewer signs off 10 generated cases against a written checklist.

## 2. Out of scope

Player-written packs; a random pack per game; per-pack difficulty tuning beyond the existing presets;
per-setting stats (the `pack` column on decisions is deferred to the stage that builds that stats view,
because the `Decider` protocol carries no game context and battery traffic has no pack at all); the
grammar of "they" (deferred since 2d, new packs use he/she only); any stage 6 item.

## 3. Build order

Fixed (format problems found on the liner should be fixed once, before the theatre):

1. Pack-hardening checks (no UI).
2. Format fixes the liner needs (section 6, "Format fixes"), with castle byte-compatibility proven.
3. Pack choice through the registry, API, MCP result, title screen.
4. Ocean liner pack.
5. Theatre pack.

Each step is shippable on its own and gets its own plan, task reviews and a final review, as in stage 4.
Step 3 is smaller than it looks: `GameHost.new_game`, the MCP `new_game` tool and `GameClient.new_game`
already take `pack`; only the API layer drops it.

## 4. Pack-hardening checks

Each is a pack-check code in the pack catalogue (today 48 codes), reported with a key path. Each ships
as a row in `tests/packs/mutations.py` with its full expected cascade (some rules overlap: a scene with
no kind already fires `SCENE_NO_CRIME_LOCATION`), and the golden catalogue is updated. Placement in `check_pack`
(`packs/runner.py`): scene location kind and record subjects join plausibility (stage 5); names, duplicate
entries and record kind keys join the template, hygiene and skin-input group (stages 3 and 4); pool sizes,
preset feasibility and roster feasibility join the capacity and matching group (stages 6 and 7, which run
only when stage 5 is clean). The plan confirms each placement against the runner.

| Check | Rule |
|---|---|
| pool sizes | `max_locations <=` number of location kinds; `max_methods <=` methods; `max_record_kinds <=` suspect- and location-subject kinds; `max_suspects <=` roles; at least 3 location kinds |
| scene location kind | every scene type has exactly one location kind |
| names | every role has at least one name; names are distinct across the whole pack after NFC and casefold (the roster compares raw text, so this is a pack rule) |
| duplicate entries | no duplicate keys inside a scene's lists, nor in role `record_kinds` / `motive_types`, nor trace / record `location_kinds` (`SetTexts` sorts but does not dedupe) |
| preset feasibility | for every claimed preset and every reachable count of location-subject record kinds, `generate.facts.feasible_depths(spec, location_records)` is non-empty. The check calls that function, so the closed form (including `L <= 2M`) cannot drift from the generator |
| roster feasibility | a walk of every reachable draw (hosting scene x S-subset of eligible roles x record kinds with holders and secrets x M-subset of allowed methods) finds a location subset meeting the roster contracts (roster.py: c, b', g') and a feasible depth. Includes the generator's trace rule (a trace whose kind the scene allows and that fits a chosen non-scene location); does not repeat `SCENE_METHOD_IMPOSSIBLE`. Budget `ROSTER_CHECK_BUDGET = 1_000_000` work units (one per draw, per visited record-kind subset and per location-subset check); a preset over budget is `PRESET_UNSUPPORTED` with that reason. Skipped when `CAPACITY_EXCEEDS_POOL` is reported. The castle's walk draws, pinned by `tests/packs/test_feasibility.py`, are 5950 (short), 2429 (standard) and 72 (long); the same walks cost 6168, 2544 and 86 work units |
| record kind keys | every kind matches `[a-z0-9_]{1,30}`, so `n_<kind>` is a valid id (`ID_PATTERN` is `[a-z][a-z0-9_]{1,31}`) |
| record subjects | no `event`-subject record kind (policy check: the roster already skips them) |
| size budget | roles and motives stay inside the matching budget `C(roles, S) x P(motives, S) <= 5,000,000` (already `PRESET_UNSUPPORTED`; the spec only states it as a target for authors, section 6) |

Constraints: the castle loads with no new errors or warnings (the reviewer's probes found none of these
rules rejects it); `castle_stages.json` is byte-identical when regenerated. A check that would reject the
castle is a spec bug: stop and rule on it. Several of these rules exist today only as castle tests
(`tests/packs/test_castle.py`); each is moved into a pack check, and the castle test is left as a
regression guard.

## 5. Pack choice

**Pack metadata.** `[meta]` gains `title` and `blurb`. They are optional in the `Pack` schema (so the pure
`load_pack` and the test fixtures stay valid) and required by the registry (`BuiltinPackError`). Both go in
`META_FIELDS` and stay out of `skeleton_view`, so they do not change any skeleton hash.

**Registry.** A bundled-pack registry lists `gumshoe/cases/packs/*.toml` with id, title, blurb and the
presets in `capacity.hosted_specs(pack)`, loading and checking each pack once. It asserts `pack.id` equals
the file stem. The host resolves packs only from this registry, never from the filesystem after startup.
One `DEFAULT_PACK = "castle"` constant is imported by `host.py`, the MCP tool, `agent/game.py` and the CLI
(tests are exempt). Every bundled pack must claim `standard`, which stays the default preset.

A bundled pack that fails its checks stops the API, the MCP server and the CLI from starting, with a message
naming the pack and the issue. Rationale: a CI test loads every bundled pack, so a broken pack cannot ship.
(Owner may prefer to log it, leave that pack out and keep castle up; recorded as a ruling to review.)
Bad-pack fixtures never live in `gumshoe/cases/packs/`.

**API.**
- `NewGameBody.pack: str = Field(DEFAULT_PACK, pattern=r"^[a-z][a-z0-9_]{0,31}$")`. Membership in the
  registry is checked before `_admit_game` (no quota is charged for an unknown pack), with a fixed message
  ("unknown setting") that never echoes the input. `bad_argument` maps to 422.
- A preset the pack does not host: 422 `bad_argument`, naming the pack's presets.
- `GET /api/meta` gains `packs: [{id, title, blurb, presets}]`; the old `presets` and `default_preset` stay
  for old clients and describe the default pack.
- `NewGame` and `NewGameView` gain `pack` (and `preset` from `case.spec.preset`, which also fixes the
  "loaded" label), so a loaded game knows its pack. This changes the MCP tool output and
  `tests/agent/fakes.py`.
- `GameSummary` (the open-games list) and `SaveSummary` carry `pack` and `setting` (title); a pack id the
  server no longer has is shown as the id.
- `info.py`'s `PACK` goes away. `docs/superpowers/specs/2026-10-13-api-contract.md` is updated.
- Locked-name redaction is unchanged and applies to every pack. The locked-names guard tests are
  castle-literal (seed 5, "Chapel of Saint Anne"); they become data-driven (a seed and place found from
  the case) so they run on each pack.

**Saves.** Every save already stores the pack (`SaveFile.pack`, required); there is no migration and no
"old save without a pack". The real risk is different: `regenerate` refuses a save when the pack's
`skeleton_hash`, `skin_rev` or any generated text differs, and the host requires the rebuilt case to match
byte for byte. So every stage 5 change to the castle (including the checks and the format fixes) must leave
the castle's skeleton hash, `skin_rev` and generated text byte-identical, proven by a committed
pre-stage-5 castle save fixture that loads. Breaking that is an owner decision (bump `skin_rev` and accept
that old saves are refused).

**Title screen.** A setting picker beside the preset picker, filled from `/api/meta`; the preset choices
follow the selected pack; the last choice is remembered in `localStorage` (try/catch, fall back to castle).
The saves and open-games lists show each setting.

## 6. The packs

**Format fixes (before the liner).** `{place.in}` is hard-coded to "in" (`skin_slots.place()`), so the liner
would read "in the bridge" and the theatre "in the stage". The fix (a per-entry preposition, or an
equivalent) must keep wording-only fields out of `skeleton_view` (which dumps whole entries) and leave every
castle text unchanged. It is planned and reviewed as its own step so castle compatibility is ruled on once.
Any further format gap the liner exposes joins this step. Done in 5b: `Entry.prep`, location names only; the castle is unchanged.

**Authoring workflow (per pack).** A subagent drafts the TOML against the format; load checks run; `smoke`
runs; the quality tests run; an independent reviewer reads 10 generated cases against a written checklist
(polarity by what is described never by "not" or "no", places and times make sense, tone fits the setting,
names fit the setting, no culprit tell); fixes land; then the pack ships.

**Quality tests run on every bundled pack.** The setting-neutral tests are parametrised over the bundled
packs: the rules in `tests/packs/test_castle.py` and `test_castle_skin.py` that are not castle-specific,
`tests/generate/test_skin_lint.py`, `test_skin_statistics.py` (150 seeds) and `test_placement_symmetry.py`
(1,500 seeds, the truth-symmetry classifier tests). Castle-flavoured assertions (for example "victims are
lords") stay castle-only. A new pack could otherwise introduce a culprit tell that none of them would catch.

**Size targets.** The matching budget bounds a pack: for `long` (7 suspects) target at most 10 roles and 8
motives (castle: 8 and 8); for `standard` (5 suspects) at most 10 roles and 9 motives. A location kind appears at most once per case and `long` needs 6 location kinds, so a pack claims `long` only
with at least 6 location kinds, `standard` with at least 4 (the presets draw 6 and 4 to 5; `short` draws 3). Each pack states its `[capacity]` and the
presets it claims; it claims only what the checks prove.

**Ocean liner.** Four dinner-sitting-style slots. Place kinds such as promenade deck, first-class lounge,
cabin corridor, bridge, galley, engine room, cargo hold (at least 6 if it claims `long`). Roles such as
steward, purser, stoker, stewardess, radio operator, card sharp and passengers. Motives and methods suited
to a ship.

**Theatre.** Slots are acts, rehearsal and the interval (acts as slots fit the format: 4 slots with `at`
and `during`, and the crime slot is drawn from 1..slots-2). Place kinds such as stage, wings, dressing
room, the flies, box office, orchestra pit, green room. The theatre is second because it follows whatever
the liner exposes, not because the stage is a format problem.

**Acceptance per pack.**
- zero load errors and warnings;
- `python -m gumshoe.cases smoke --pack <id> --preset <p> --seeds 360` exits 0 for every claimed preset
  (its `ok` already requires no failures, mean attempts at most 2 and max at most 10; 360 seeds is the
  size used for the castle, about 2 minutes per pack across three presets);
- the quality and symmetry tests of this section pass on the pack;
- the 10-case review (checklist above) finds no incoherent case.
There is no mean-actions tool for a pack today; this spec does not add one (solvability is guaranteed by
the strict validator inside the pipeline).

## 7. Risks

- **Content volume.** Each pack is roughly 800 lines of prose. The checks and the review loop control cost;
  a thin pack repeats names and clues, which is the problem stage 5 exists to fix.
- **Castle compatibility.** Any castle edit can break existing saves (section 5). The format fix is the
  likeliest cause; the committed save fixture and `castle_stages.json` are the guard.
- **A check wrongly rejects the castle.** A spec bug (section 4).
- **Matching budget and location kinds** silently cap the presets a pack can claim (section 6); the
  checks report this as `PRESET_UNSUPPORTED`, so the pack claims fewer presets, not a broken one.
- **Registry fail-fast** stops every process if a bundled pack is broken (section 5); CI loads all packs.
- **Tone drift between packs for the decider models.** Visible only once per-setting stats exist (deferred).

## 8. Testing

Test first, as always. Per check: a mutation row with its cascade. Registry: loads all bundled packs;
`pack.id` equals the stem; a broken bundled pack stops startup; metadata required. API: pack choice,
unknown pack (no quota charged, fixed message), pack pattern, wrong preset (422), loaded game reports its
pack, a real game created on each bundled pack (Playwright uses `e2e/fake-api.mjs` and never exercises real
generation, so this is a Python API test), the committed pre-stage-5 castle save loads, the locked-names
guard on each pack. Frontend: setting picker, preset list follows the pack, remembered choice, saves and
open-games lists show the setting, an unknown pack id is shown as the id. Playwright: pick each setting.
