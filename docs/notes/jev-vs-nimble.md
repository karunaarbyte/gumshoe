# Jev vs Nimble: first observations (2026-10-01)

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
