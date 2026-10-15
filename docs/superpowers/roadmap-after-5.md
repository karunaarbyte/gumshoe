# Gumshoe roadmap after sub-project 5

Status on 2026-10-15: sub-projects 1 to 5 (decision layer, case engine, MCP server, agent loop and API,
React UI) are merged to local `main` (b8097e7), unpushed. This is the consolidated order of what is left.
Each numbered stage gets its own spec, plan and build cycle where it is more than a small fix.

## Order and why

| # | Stage | Size | Why here |
|---|---|---|---|
| 0 | Housekeeping | small | Protects the work already done. Nothing else depends on it, so do it first. |
| 1 | Make the game playable end to end | small | Two defects hide how the game really plays, so content work would be built on a false picture. |
| 2 | 6a: Game content and help | medium | The biggest gain for a player, no security impact, no contract change. |
| 3 | Stats page and the Jev vs Nimble verdict | medium | The project's original purpose. Needs real play data, which stage 2 makes worth collecting. |
| 4 | 6b: Public hardening | large | Only needed before anyone else can reach the API. Changes the contract, so it comes after the game is worth exposing. |
| 5 | 2e: More packs | large | Replayability. Pack hardening must come before new packs. |
| 6 | Polish and backlog | small, any time | Independent small items; pull one in whenever a stage is waiting. |

## Stage 0: Housekeeping

- Push `main` (check the remote first).
- Delete merged feature branches (`feat/agent-core-4b`, `feat/api-4c`, `feat/hardening-4d1`,
  `feat/agent-api-hardening-4d2`, `feat/web-ui-5`, older merged ones) and prune scratch worktrees
  (`scratch/*`, the `prunable` entries in `git worktree list`).
- Commit the untracked plans and specs in `docs/superpowers/` (the user commits docs manually).

## Stage 1: Make the game playable end to end

1. **Dialogue model.** In the live run every suspect answered with the canned line "looks away and says only:
   ale" (reply `source: canned`). Find out why the persona models (Ollama `ministral-3:14b`, `gemma4:12b`)
   did not answer: Ollama not running, a model not pulled, a timeout, or a bug. Fix or document it. Until this
   works, the game cannot be judged: suspects are the heart of it.
2. **Typed `yes`.** A typed "yes" with a confirmation waiting was classified as a new accusation, which cancelled
   the pending one. The Yes button (`/confirm`) works. Make a bare yes resolve deterministically, using the
   existing `is_bare_yes` helper, before the model is asked, whenever a confirmation is pending.

## Stage 2: 6a, game content and help

- **Helpful fallbacks.** Replace "I am not sure what you want to do" and the one-line `HELP` with a state-aware
  nudge: places not searched yet, suspects that can be questioned, whether records or an accusation are
  available, with example phrases. Deterministic, no model call.
- **Answers from known facts.** Questions such as "what happened", "who is the victim" or "what do I know" are
  answered from the case intro and the notebook, never from hidden case data. Add a test that no answer can
  contain unrevealed facts.
- **Unlock clarity.** Say why a suspect or an accusation is not available yet ("you have no lead on Gilbert yet;
  question suspects or read records").
- **Help box.** Rewrite to match the real rules: records are read about a suspect or place, an accusation needs
  a lead, the Yes button is the reliable confirmation, and what the red strings and card clicks mean.
- Spec this as a short design (bounded) unless the fallback design grows past the agent's turn code.

## Stage 3: Stats page and the Jev vs Nimble verdict

- Play a number of games with shadow mode on, so there is data (the stats API already exists).
- Add an aggregate stats page to the UI: agreement rate, latency, cost per node, per-node disagreements, with a
  drill-down to the decision trace.
- Write up the verdict in `docs/notes/jev-vs-nimble.md`: where Jev earns its cost and where Nimble is enough.
- Stage 2b item 2d-4 (the stats digest pin) is picked up here if the page needs it.

## Stage 4: 6b, public hardening

Architectural. Own spec, security review, plan.

- **Identity.** Anonymous server-issued session token (signed, random), with a coarser per-IP limit as a backstop.
  Games, saves and quotas belong to a session, so one player cannot read, delete or replay another's game by
  guessing an id. Accounts are out of scope until leaderboards or cross-device saves are wanted.
- **Limits.** Per-session turn rate and a daily Jev budget; per-session game creation rate; per-session open-game
  and save caps (today the caps are global: 1000 games, 500 saves, so one client can lock everyone out);
  `429` responses the UI shows as a friendly message; a global budget cutoff that switches the game "off"
  gracefully.
- **Lifecycle.** Expire idle games so abandoned ones free their slots.
- **Input.** Keep the existing validation (seed 0 to 2^63-1, body size cap, turn length). Add tests that chat
  text cannot be used to read hidden case data or other sessions' games, and that a tampered save is
  rejected (already enforced by regeneration, keep that test).
- **Exposure.** The API currently binds to loopback only with no CORS; decide the deployment shape (one machine,
  games in memory), add HTTPS and the CORS policy, and serve the UI build.
- Open decisions for the spec: the actual numbers, the global-budget behaviour, session token transport.

## Stage 5: 2e, more packs

- First the pack-hardening list carried from the 2d-2 spec (event-kind rejection, one location kind per scene,
  name and Unicode checks, coverage, enumeration budget).
- Then one or two new packs for variety. Replayability depends on this far more than on seeds, which only
  choose among the existing pack's names, places and clues.

## Stage 6: Polish and backlog (pull in any time)

UI:
- Red strings cross each other.
- Card drag offset while the board scrolls; toast timers never cleared.
- Older chat results take a lot of room (collapse them).
- No mobile layout (the desk needs about 1100px).

Backend (from the 4d notes):
- The gate misses accents, leetspeak and combining marks.
- A full saves folder returns 500 `bad_save` (a 409 or 429 would be better).
- stat/open FIFO race; `os.replace` fallback stub.
- An accusation completing right as the 120s turn net fires is reported as failed.
- `/api/decisions` error text can quote a decider API body.
- Logs carry tracebacks, against the plan's rule.
- CORS preflight rejections lack `{code, message}`.
- A loaded given-up game reads `lost`.

## Not planned

Accounts and login, internationalisation, autosave, native mobile.
