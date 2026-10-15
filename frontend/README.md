# Gumshoe web UI

The noir case-file front end for the Gumshoe API. React, TypeScript, Vite, Tailwind, Framer Motion
and TanStack Query. The only interface to the backend is the API contract in
`docs/superpowers/specs/2026-10-13-api-contract.md`.

## Run it

Two terminals, from the repo root:

```bash
uv run gumshoe-api          # the API on 127.0.0.1:8000 (billed: every turn calls Jev)
cd frontend && npm ci && npm run dev   # the UI on http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000` (set `GUMSHOE_API_URL` to point it
elsewhere), so no CORS setup is needed. The API is loopback-only with no authentication; do not
expose either server.

## Scripts

| command | what it does |
|---|---|
| `npm run dev` | Vite dev server on port 5173 |
| `npm test` | Vitest unit and component tests (jsdom; no network): 216 tests in 16 files |
| `npm run typecheck` | `tsc` over `src/`, `e2e/` and the configs |
| `npm run build` | typecheck, then the production build in `dist/` |
| `npm run e2e` | the Playwright smoke test (2 tests) against `e2e/fake-api.mjs` (needs `npx playwright install chromium` once); same as `npx playwright test` |
| `npm run fake-api` | the scripted fake API on port 8765, to click through the UI for free |

No automated test ever talks to the real backend: the unit tests replay fixtures and the smoke
test starts its own fake API (port 8765) and its own dev server (port 5174) pointed at it. It
never uses 5173 or 8000, so it is safe to run while the real servers are up.

## Manual checklist against the real backend

Run this once per release, by hand, because every turn is billed. Start the API with a working
decider (`GET /api/health` says `"game": "on"`), then `npm run dev`.

1. Title screen: presets list comes from `/api/meta`; health banner absent; saves and open games
   listed.
2. New case with an empty seed: the desk opens, suspects across the top of the board, locked
   cards face down.
3. Type `search <a place from the board>`: the notebook and the board gain facts; the trace drawer
   lists the turn and its decisions (Jev and Nimble side by side, cost and latency filled).
4. Ask a suspect a question: a reply with the speaker's name; a locked suspect answers as
   unavailable.
5. **Open question from the spec (section 5.2):** type `I accuse <a suspect>` with no method or
   motive. The agent answers with picker rows for How and Why. Click a How option, then a Why
   option. Record here whether the agent accepted the bare option name:
   - accepted: nothing to change;
   - not accepted: change the one line in `src/chat/pickerText.ts` to return
     `` `I think it was ${option.name}` `` for `how` and `why`, re-run `npm test`, and repeat this step.
6. When the confirmation card appears, reload the page: the card comes back with live Yes/No.
7. Type `yes`: the turn carries the waiting `pending_id` (check the request body in the browser's
   network tab) and the accusation runs.
8. Play to an ending: the ceremony shows CASE CLOSED or FILE REMAINS OPEN, then the reveal.
9. Start another case, press Save: a toast names the save. Drag a card and draw a thread first;
   after Load from the title screen the arrangement comes back.
10. Stop the API mid-turn (Ctrl-C while the typing indicator shows): the UI says the connection
    was lost; restart the API and reload: the title screen says the game has ended.
11. Give up (`I give up`, then Yes): the ceremony says FILE REMAINS OPEN.

## Known limits

- Desktop first: the desk has a minimum width of 1100px and there is no mobile layout.
- No stats dashboard.
- No autosave: a game is saved only when you press Save.
- The board layout (card positions and player threads) lives in the browser's localStorage, keyed
  by game id. Save copies it under the save name; Load restores it into the new game.
- A game that was never saved and is lost to a server restart loses its arrangement.
