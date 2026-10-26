# Stage 5: pack hardening, pack choice, and two new packs (design)

Status: design approved in conversation 2026-10-26, awaiting written-spec review. Implements stage 5 of
`docs/superpowers/roadmap-after-5.md`. Builds on the pack format (2c), the generator (2d) and the
pack-hardening list in `2026-10-05-generator-evidence-2d2-design.md` section 10.

## 1. Goal and success criteria

Replayability today depends on one pack (`castle`): seeds only reshuffle its names, places and clues.
Stage 5 adds two new settings, an **ocean liner** and a **1920s theatre**, lets the player choose the
setting, and first makes the pack checks strict enough that a bad pack is refused at load, not halfway
through generating a case.

Done when:
- every item of the 2d-2 hardening list is a pack check with a test and a bad-pack fixture;
- the castle still loads with zero errors and its skeleton digest is unchanged;
- the API and title screen offer the three settings and the choice is saved with the game;
- each new pack loads with zero errors, generates without failure over seeds 0-359 on every preset
  it claims, and passes an independent wording review of 10 generated cases.

## 2. Out of scope

Player-written packs; a random pack per game; per-pack difficulty tuning beyond the existing presets;
any stage 6 item.

## 3. Build order

Fixed (chosen over parallel packs because format problems found on the liner should be fixed once,
before the riskier theatre):

1. Pack-hardening checks (no UI).
2. Pack choice through API, saves, title screen.
3. Ocean liner pack.
4. Theatre pack.

Each step is shippable on its own and gets its own plan, task reviews and a final review, as in stage 4.

## 4. Pack-hardening checks

Each is a pack-check code in the pack issue catalogue, reported with a key path like the existing 34
codes, and each ships with a test written first plus a fixture that triggers exactly that code.

| Check | Rule |
|---|---|
| few locations | at least 3 locations |
| scene location kind | every scene type has exactly one location kind |
| names | roles have at least one name; enough distinct names across eligible roles; names equal after NFC are duplicates |
| duplicate keys | no duplicate keys inside a scene's lists |
| preset feasibility | every claimed preset has a feasible depth (closed form, 2d-2 section 6) |
| fact supply | enough supports facts to fill every location (`L <= 2M`) |
| method traces | every method has a trace that fits the scene, and a non-scene chosen location |
| suspect coverage | suspect-kind coverage of the roster (2d-2 section 4) |
| record kind keys | valid neutral fact ids (`n_<kind>`: lowercase, at most 30 characters) |
| record subjects | no `event`-subject record kind (stages support suspect and location subjects only) |
| enumeration budget | the location enumeration stays inside the generator's budget |

Constraints: castle loads with no new errors or warnings it did not already have; `Output.digest` and
the pinned castle skeleton digest do not change. A check that would reject the castle is a spec bug,
not a pack bug: stop and rule on it.

## 5. Pack choice

**Pack metadata.** `[meta]` gains `title` (shown to the player) and `blurb` (one sentence). `presets`
already exists. Both new fields are required for bundled packs; a pack without them is a load error.

**Registry.** A bundled-pack registry lists the packs in `gumshoe/cases/packs/*.toml` with id, title,
blurb and presets, loading and checking each once at startup. A bundled pack that fails its checks
stops the server from starting with a message naming the pack and the issue.

**API.**
- `POST /api/games` takes an optional `pack` (default `castle`). Unknown pack: 400 `bad_argument`.
  A preset the pack does not claim: 400 `bad_argument` with the pack's presets in the message.
- `GET /api/meta` gains `packs: [{id, title, blurb, presets}]`; `presets` and `default_preset` stay
  for old clients and describe the default pack.
- The game state and the saves list carry `pack` (id) and `setting` (title). Old saves have no pack
  recorded as such and count as `castle`.
- `info.py`'s `PACK` constant goes away; nothing outside the registry names `castle`, except the
  default.
- Locked-name redaction is unchanged and applies to every pack (the guard tests run on each).

**Decisions and stats.** A decision records the pack id so the stats page can later compare models
per setting. Adding the column is a migration of `decisions.db` that keeps old rows (pack `castle`).

**Title screen.** A setting picker beside the preset picker, filled from `/api/meta`. The preset
choices follow the selected pack. The last choice is remembered in `localStorage` (try/catch, with a
fallback to castle). The saves list shows each save's setting.

## 6. The packs

**Authoring workflow (per pack).** A subagent drafts the TOML against the pack format spec; the load
checks run; the smoke and statistics tools run (solvable on every claimed preset, mean actions per
preset, wording hygiene); an independent reviewer reads 10 generated cases for sense and tone; fixes
land; then the pack ships. The castle's wording rules (`2026-10-05-castle-evidence-wording-2c1b`,
including: polarity by what is described, never by "not" or "no") apply to every pack.

**Ocean liner.** Four dinner-sitting-style slots. Decks, cabins, the bridge, the galley and the
engine room as places. Roles such as steward, purser, stoker, stewardess, radio operator, a card
sharp, passengers. Motives and methods suited to a ship (nothing that needs a place the pack lacks).

**Theatre.** Slots are acts, rehearsal and the interval. Places include the stage, wings, dressing
rooms, the flies and the box office. Its fixed stage is the reason it comes second: anything the
liner exposes in the format is fixed once, then the theatre follows.

**Capacity.** Each new pack meets the existing `[capacity]` shape (suspects, locations, methods,
record kinds) and claims only the presets its check proves feasible; a pack that cannot host `long`
does not claim it.

**Acceptance per pack.** Zero load errors; `smoke` over seeds 0-359 on every claimed preset with no
generation failure; the wording gates the castle passes; the 10-case review finds no incoherent case.

## 7. Risks

- **Content volume.** Each pack is roughly 800 lines of prose. The checks and the review loop are the
  cost control; there is no shortcut by thinning a pack, because thin packs repeat names and clues.
- **A check wrongly rejects the castle.** Treated as a spec bug (section 4).
- **The theatre does not fit the format** (acts as slots, a fixed stage as place). The liner comes
  first so the format is fixed before the theatre; if the theatre still does not fit, stop and bring
  the problem to the owner rather than bending the pack.
- **Saves and stats migration.** Old saves and old decision rows must keep working (default castle);
  a test loads a pre-stage-5 save.
- **Tone drift between packs** for the decider models. The stats page's per-setting split (later)
  is how that would show.

## 8. Testing

Test first, as always. Per check: a failing fixture, then the check. Registry: loads all bundled
packs; a broken bundled pack stops startup. API: pack choice, unknown pack, wrong preset, old save
without a pack, the locked-names guard on each pack. Frontend: setting picker, preset list follows
the pack, remembered choice, saves list shows the setting. Playwright: start a game on each setting.
