# Shadow-mode stats: first real run (2026-10-01)

Setup: `python -m gumshoe.stats battery --rounds 3` = 12 fixed player inputs x 3 rounds = 36 decisions,
demo question set (`intent` choice, `needs_interrogation` noul, `urgency` score), Jev (`jev-latest`, hosted) as
primary and Nimble (`nimble:latest`, local via Ollama) as shadow, each decision settled before the next one
starts. Numbers come from `GET /api/stats/decisions`. 36 samples is still small; read as direction, not proof.

## Headline numbers

| | Jev (primary) | Nimble (shadow) |
|---|---|---|
| calls / errors / cold | 36 / 0 / 1 | 36 / 0 / 1 |
| latency p50 (warm) | 348 ms | 648 ms |
| latency p95 (warm) | 446 ms | 662 ms |
| latency p95 incl. cold call | 530 ms | 669 ms |
| mean tokens in / out | 429 / 84 | 979 / 4 |
| mean confidence | 0.776 | 0.609 |

Agreement over 36 compared decisions: **0.667** overall. By question: intent 0.75, needs_interrogation 0.833,
urgency **0.417** (score compared by spread < 0.5 of a level).

## What stands out

1. **Nimble is steady, Jev is faster.** Nimble's warm p50 and p95 are 648 and 662 ms (a very tight band), Jev's
   348 and 446 ms. The ~1.6 s I saw earlier from one-shot CLI runs was fresh-process overhead (new connection),
   not model time. Local Nimble is ~1.9x slower at the median, with far less variance than a network call.
2. **Cold calls barely matter here.** Only the first call of each backend was cold (the run is continuous). The
   3.8 s cold Nimble call from the first session would show up as a spike in `include_cold=true`; this run's cold
   call was cheap because Ollama already had the model loaded. Test again after >5 min idle.
3. **Token counts are not comparable across backends.** Nimble reports ~979 in / 4 out for the same inputs where
   Jev reports ~429 / 84. Compare each backend to itself over time, not to the other.
4. **Urgency (score) is where they diverge.** 0.417 agreement vs 0.75 and 0.83 on the other two. Earlier eyeball
   showed Nimble compressing scores toward ~1; the fixed-tolerance comparison confirms the scores rarely land
   within half a level of each other. Next experiment: compare the *ranking* of inputs by urgency instead of
   absolute values, since a monotonic offset would still be useful for routing.
5. **Jev is more confident on average** (0.776 vs 0.609) but earlier we saw it is also confident on nonsense
   ("asdf"). Confidence needs per-node calibration against ground truth before it gates anything.

## Failure paths (verified live with throwaway databases)

- Wrong Jev key: 12/12 primary calls `HTTP 401`, every decision flagged `fallback`, answered by Nimble.
- Ollama unreachable: Jev answered everything, 12 shadow errors recorded (`cannot reach ... (ConnectError)`).
- Both broken: exit 1, one readable message with both causes, all 24 failed calls recorded.

## A bug the fakes could not find

The first live run recorded only **13 of 36** Nimble calls. The battery fired decisions back to back; Jev returns
in ~0.4 s but the local model handles requests one at a time, so shadow calls queued up and the final `aclose()`
grace period cancelled the backlog. Fix: the battery now `drain`s (settles) after every decision, like a human
pacing real play. Lesson: backpressure is invisible to unit tests with instant fakes.

## Open questions

- Does richer `criteria` text close the Nimble `action`/`meta` gap seen earlier?
- Run the battery after >5 minutes of Ollama idle to capture a real cold Nimble call and its effect on p95.
- How does agreement change with more rounds (is 0.667 stable at 300 samples)?
- Rank-based urgency agreement (see point 4).
