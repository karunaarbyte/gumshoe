# Jev vs Nimble: verdict from the real game (2026-10-15)

Data: 320 decisions from 12 played games (`data/decisions.db`), shadow mode on: Jev (hosted) decided, Nimble
(`nimble:latest`, local via Ollama) ran beside it, recorded only. Numbers come from `GET /api/stats/decisions` and the
`#/stats` page. Agreement is "gave the same answer", not "was right": there is no ground truth yet.
Jev prices used: $0.042 per million input tokens, output free (secondary sources, not TypeSafe's own page: confirm).

## The short answer

- **Jev is the right primary for the player-facing decisions.** About 0.3 s median at every node, no errors in 320
  calls, and the whole run cost about **$0.016** in input tokens. Cost is not a reason to avoid it.
- **Nimble is not ready to be the primary for `understand` or `parse_accusation` on this setup.** Its median was
  12.5 s at `understand` and 26 s at `parse_accusation`, and 69 calls hit the 30 s limit. The game cannot wait that
  long for a player's message. Nimble is usable where the input is short and a few seconds is fine (`post_check`:
  5 s median, 0 errors, 90% agreement), but it is still 16x slower than Jev there.
- **Where they agree, the choice does not matter; where they disagree, we do not yet know who is right.** See below.

## Numbers

| Node | Compared | Agreement | Jev p50 / p95 | Nimble p50 / p95 | Nimble errors |
|---|---|---|---|---|---|
| understand | 165 of 228 | intent 72%, target 86%, weight 83% | 317 / 401 ms | 12.5 s / 28.6 s | 63 (28%) |
| parse_accusation | 18 of 24 | who 100%, why 100%, how 89% | 306 / 356 ms | 26.0 s / 30.0 s | 6 (25%) |
| post_check | 68 of 68 | guilt/blame 100%, contradicts 81% | 301 / 405 ms | 5.0 s / 5.3 s | 0 |

Weight is compared in bands; Nimble scores about 0.38 of a level higher than Jev on average.
Input tokens are not comparable between backends (Nimble reports ~4000 per `understand` call, Jev ~1400).

## What the disagreements look like (`understand` intent)

- **Search was the weak spot for Nimble.** 42 of the 64 "search" decisions had a Nimble error, and where it answered
  it split between search (14), interrogate, records and talk. Most of the "disagreement" here is missing data.
- **Records and accuse agree well** (29 of 36 records; all 21 accuse decisions Nimble answered matched, 3 more errored).
- **`other` and `meta` are fuzzy for both.** Jev said `other` on 9 messages where Nimble said records, accuse or meta.
  These are the unclear messages the game answers with guidance anyway, so little rides on them.

## Caveats (read before trusting any latency number)

1. **The latency comparison is confounded.** Nimble shared one Ollama with the two persona models, so a persona
   reply could evict Nimble or queue ahead of it. The 30 s errors are partly that, not Nimble alone. A clean run
   (Nimble on its own Ollama, personas on another) was planned but not done: it needs a Jev key and `SHADOW_RUN=true`.
   Even then both models share one 24 GB machine, so contention for GPU and memory remains.
2. **Agreement is not accuracy.** 165 compared of 228 means 28% of `understand` decisions have no Nimble answer.
   Someone should label a sample of the disagreements by hand before saying either model is better.
3. **One player type.** The 12 games were scripted with varied phrasing, not real players.
4. **Prices are from secondary sources**, and the free output price may change.

## Next experiments

1. Clean latency run with two Ollama instances (`OLLAMA_HOST=127.0.0.1:11435 ollama serve` for Nimble, then
   `NIMBLE_BASE_URL=http://localhost:11435/v1`). If Nimble then answers in ~1-2 s with few errors, it becomes a
   viable fallback or a primary for offline play.
2. Hand-label 50 `understand` disagreements to see who is right.
3. Try richer criteria text for the `search`/`records` intents before blaming the model.

---

# Earlier observations (2026-10-01, 8 inputs, anecdote)

Setup: demo question set (`intent` choice with 4 options, `needs_interrogation` noul, `urgency` score with 5 levels),
8 player inputs, one `compare` run each (fresh process per input, both backends called concurrently).
Jev = hosted `jev-1.13.0`; Nimble = local `nimble:latest` (qwen35 9B Q8) via Ollama. 8 inputs is anecdote, not evidence.

## Agreement (picks; score rounded to nearest level)

| Question | Agree | Notes |
|---|---|---|
| intent | 5 / 8 | Disagreements: "search the study" (Nimble `meta` 0.52, Jev `action` 1.00), "look around, maybe talk to someone" (ambiguous), "sneak in and pick the lock then question the cook" (compound) |
| needs_interrogation | 6 / 8 | "I accuse the butler!" (Nimble no 0.33, Jev yes 0.80), "look around..." (ambiguous) |
| urgency | 3 / 8 | Nimble compresses toward ~1 (range 0.15 to 2.20, mostly 0.8 to 1.6). Jev spans 0.00 to 3.11 |

## Observations

1. **Clear physical actions:** Nimble labelled "I search the study for fingerprints" as `meta` (0.52), and in an earlier
   run 0.76. Jev said `action` 1.00. The `action` vs `meta` criteria ("Physical action in the world" vs "Game or UI
   command") may be too thin for the 9B; test richer criteria before blaming the model.
2. **Nonsense input ("asdf"):** both chose `meta`, because the question has no "other" option. Nimble confidence 0.41,
   Jev 0.71. Jev is *more* confident on garbage, so confidence alone is not a safe gate. Add an explicit `other`
   option to the real intent question (TypeSafe guidance: include a no-match outcome).
3. **Confidence as an uncertainty signal:** the ambiguous inputs had the lowest picks' probabilities on both
   (0.51 to 0.61 Nimble, 0.55 Jev) and the clear ones were near 0.95 to 1.00, so probabilities help; Jev's
   `confidence` field on nonsense does not.
4. **Compound requests** ("pick the lock then question the cook") split a single `choice`. The real pipeline
   should ask several independent noul questions over the same state (needs_lockpick, needs_interrogation, ...)
   and chain tools from the yes answers, not rely on one choice.
5. **Latency (not like-for-like):** Jev 494 to 664 ms every run (network + TLS, fresh process). Nimble 731 to 1595 ms
   in fresh processes; ~650 ms for a second call in one process; 3.8 s on the first call after idle (model load).
   The uniform ~1.59 s is suspicious (connection setup? Ollama scheduling?). Do not trust it until Plan 1b records
   many calls and we look at p50/p95 and exclude first-after-idle calls.
6. **Tokens:** Nimble reports 1000 in / 4 out; Jev 437 in / 84 out for the same request. Different meanings; compare
   within a backend only.
7. **Determinism:** Nimble repeated identical scores; Jev's urgency drifted slightly between identical calls
   (1.20 vs 1.24). Small, but agreement thresholds should not sit exactly at a rounding boundary.

## Open questions for later

- Does richer `criteria` text close the Nimble `action`/`meta` gap?
- What do Nimble's ~1.6 s fresh-process calls look like over 100 calls (warm model, shared client)?
- Which nodes in the real pipeline can tolerate Nimble's score compression (route/dramatic weight) and which can't?
