// A scripted stand-in for the Gumshoe API, for the Playwright smoke test only. It never calls
// a model and never touches the real backend. Run: node e2e/fake-api.mjs [port]
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

// the same fixtures the unit tests use, so the two cannot drift
const fixture = (name) => JSON.parse(readFileSync(new URL(`../src/test/${name}`, import.meta.url), 'utf8'));

const PORT = Number(process.argv[2] ?? process.env.FAKE_API_PORT ?? 8765);
const GAME = 'e2e-game';

const brief = {
  intro: 'Lord Ashby lies dead in the long gallery.',
  suspects: [
    { number: 1, handle: 's1', name: 'Mr Grey the butler', description: 'Stiff and correct.', locked: false },
    { number: 2, handle: 's2', name: '', description: '', locked: true }, // locked: sent without its name
  ],
  locations: [{ number: 1, handle: 'l1', name: 'Long gallery', description: 'Portraits and a body.', locked: false }],
  record_kinds: [{ key: 'letters', label: 'Letters' }],
  attempts_left: 3,
  status: 'playing',
};
const reveal = { culprit: 'Mr Grey the butler', method: 'poisoned port', motive: 'an unpaid inheritance', secret: 'he is the late lord’s son' };
const confirmText = 'Accuse Mr Grey the butler, by poisoned port, for an unpaid inheritance?';

let game = null; // { pending, outcome, facts, turns }
const PACKS = [
  { id: 'castle', title: 'The Castle', blurb: 'A murder at a country house.', presets: ['short', 'standard'] },
  { id: 'liner', title: 'The Liner', blurb: 'A death on an ocean liner.', presets: ['standard'] },
];
let chosenPack = 'castle'; // the pack of the last POST /api/games
const settingOf = (id) => PACKS.find((p) => p.id === id)?.title ?? id;
let saves = []; // SaveSummary rows, newest first: a save adds one, DELETE /api/saves/{name} drops it
let requests = []; // bodies of POST /turn and /confirm, for the test to inspect via GET /__requests
// the admin routes answer a plain 404 unless this (fake) token is sent, like the real server
const ADMIN_TOKEN = 'e2e-fake-admin-token';
const isAdmin = (path) => path === '/api/stats/decisions' || path === '/api/decisions' || path.startsWith('/api/decisions/');
let authLeaks = []; // player routes that were sent an Authorization header (there should be none)

function fresh() {
  return { pending: null, outcome: 'playing', facts: [], turns: [] };
}

function state() {
  return {
    brief: { ...brief, status: game.outcome === 'playing' ? 'playing' : game.outcome === 'won' ? 'won' : 'lost' },
    notebook: { sections: game.facts.length === 0 ? [] : [{ source: 'Long gallery', facts: game.facts }], contradictions: [] },
    outcome: game.outcome,
    pending: game.pending,
    reveal: game.outcome === 'playing' ? null : reveal,
    preset: 'standard',
  };
}

const reply = (text, speaker = null) => ({
  kind: 'reply',
  speaker,
  text,
  source: 'draft',
  degraded: false,
  violations: [],
  model: 'fake',
  drafts: 1,
  latency_ms: 5,
});
const done = { kind: 'done', turn_ms: 20 };

function turnEvents(text) {
  if (/search/i.test(text)) {
    game.facts = [{ handle: 'f1', text: 'A stained glass lies by the body.', speaker: null, relates_to: ['Mr Grey the butler'], contradicted: false }];
    return [
      { kind: 'intent', decision_id: 'd-search', intent: 'search', target: 'l1', confidence: 0.94 },
      { kind: 'tool_call', tool: 'search', args: { game: GAME, location: 'l1' } },
      { kind: 'tool_result', tool: 'search', ok: true, code: null, message: null, data: { status: 'ok' } },
      reply('You find a stained glass by the body.'),
      done,
    ];
  }
  if (/accuse/i.test(text)) {
    game.pending = { pending_id: 'p-e2e', kind: 'accuse', text: confirmText, warnings: [] };
    return [
      { kind: 'intent', decision_id: 'd-accuse', intent: 'accuse', target: null, confidence: 0.9 },
      { kind: 'confirm', pending: 'accuse', pending_id: 'p-e2e', text: confirmText, warnings: [], decision_id: 'd-accuse' },
      done,
    ];
  }
  return [
    {
      kind: 'reply',
      speaker: null,
      text: 'Ask about a suspect, search a place, or accuse.',
      source: 'help',
      degraded: false,
      violations: [],
      model: null,
      drafts: 0,
      latency_ms: null,
    },
    done,
  ];
}

function confirmEvents(answer) {
  game.pending = null;
  if (answer === 'no') return [{ kind: 'cancelled' }, done];
  game.outcome = 'won';
  return [
    { kind: 'tool_call', tool: 'accuse', args: { game: GAME, who: 's1', how: 'm1', why: 'w1', confirmed: true } },
    { kind: 'tool_result', tool: 'accuse', ok: true, code: null, message: null, data: { status: 'resolved', correct: 3 } },
    { kind: 'game_over', outcome: 'won', reveal },
    done,
  ];
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(body === undefined ? '' : JSON.stringify(body));
}

const error = (res, status, code, message) => json(res, status, { code, message });

/** Streams events the way the server does, in awkward chunks, with a ping first. */
async function stream(res, kind, text, events) {
  const record = { turn_id: String(game.turns.length), kind, text, ts: new Date().toISOString(), events: [], complete: false };
  game.turns.push(record);
  res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
  res.write(': ping\n\n');
  for (const event of events) {
    const block = `event: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`;
    const cut = Math.floor(block.length / 2);
    res.write(block.slice(0, cut));
    await new Promise((r) => setTimeout(r, 30));
    res.write(block.slice(cut));
    record.events.push(event);
  }
  record.complete = true;
  res.end();
}

async function body(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return chunks.length === 0 ? {} : JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function decision(id) {
  const call = (backend, role, verdict, used) => ({
    backend,
    role,
    used,
    cold: false,
    latency_ms: role === 'primary' ? 110 : 420,
    error: null,
    input_tokens: 800,
    output_tokens: 10,
    est_cost_usd: 0.0003,
    answers: { intent: { verdict, confidence: 0.9 } },
  });
  return {
    decision_id: id,
    node: 'understand',
    ts: new Date().toISOString(),
    fallback: false,
    state_preview: 'fake',
    calls: [call('jev', 'primary', 'search', true), call('nimble', 'shadow', 'interrogate', false)],
    agrees: { intent: false },
  };
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const path = url.pathname;
  const method = req.method ?? 'GET';
  if (isAdmin(path)) {
    if (req.headers.authorization !== `Bearer ${ADMIN_TOKEN}`) return error(res, 404, 'not_found', 'Not Found');
  } else if (req.headers.authorization !== undefined && !path.startsWith('/__')) authLeaks.push(path);
  if (method === 'GET' && path === '/__auth_leaks') return json(res, 200, authLeaks);
  try {
    if (method === 'GET' && path === '/api/health')
      return json(res, 200, {
        status: 'ok',
        game: 'on',
        reason: null,
        primary: 'jev',
        shadow: 'nimble',
        persona_models: { default: 'fake', dramatic: 'fake' },
        personas: 'up',
      });
    if (method === 'GET' && path === '/api/meta')
      return json(res, 200, {
        packs: PACKS,
        presets: ['short', 'standard'],
        default_preset: 'standard',
        max_attempts: 3,
        max_turn_chars: 1000,
      });
    if (method === 'GET' && path === '/api/saves') return json(res, 200, saves);
    const saveMatch = /^\/api\/saves\/([^/]+)$/.exec(path);
    if (method === 'DELETE' && saveMatch) {
      const name = decodeURIComponent(saveMatch[1]);
      if (!saves.some((s) => s.name === name)) return error(res, 404, 'unknown_game', 'no such save');
      saves = saves.filter((s) => s.name !== name);
      res.writeHead(204);
      return res.end();
    }
    if (method === 'GET' && path === '/api/games')
      return json(
        res,
        200,
        game === null
          ? []
          : [
              {
                game: GAME,
                pack: chosenPack,
                setting: settingOf(chosenPack),
                preset: 'standard',
                outcome: game.outcome,
                attempts_left: 3,
                turn_running: false,
              },
            ],
      );
    if (method === 'POST' && path === '/api/games') {
      const made = await body(req);
      chosenPack = made?.pack ?? 'castle';
      game = fresh();
      requests = [];
      return json(res, 200, { game: GAME, brief, pack: chosenPack, preset: 'standard' });
    }
    if (method === 'GET' && path === '/__requests') return json(res, 200, requests);
    if (method === 'GET' && path === '/api/stats/decisions') return json(res, 200, fixture('stats-fixture.json'));
    if (method === 'GET' && path === '/api/decisions') return json(res, 200, fixture('disagreements-fixture.json'));
    const decisionMatch = /^\/api\/decisions\/([^/]+)$/.exec(path);
    if (method === 'GET' && decisionMatch) return json(res, 200, decision(decisionMatch[1]));
    const gameDecisionMatch = /^\/api\/games\/[^/]+\/decisions\/([^/]+)$/.exec(path);
    if (method === 'GET' && gameDecisionMatch) return json(res, 200, { ...decision(gameDecisionMatch[1]), state_preview: '' }); // redacted for players
    const m = /^\/api\/games\/([^/]+)(\/turn|\/confirm|\/turns|\/save)?$/.exec(path);
    if (m === null) return error(res, 404, 'not_found', 'no such route');
    if (game === null || m[1] !== GAME) return error(res, 404, 'unknown_game', 'no such game');
    const sub = m[2] ?? '';
    if (method === 'GET' && sub === '') return json(res, 200, state());
    if (method === 'GET' && sub === '/turns') return json(res, 200, game.turns);
    if (method === 'POST' && sub === '/turn') {
      const b = await body(req);
      requests.push({ route: 'turn', body: b });
      // a typed yes only acts when it carries the waiting id, as the real server requires
      if (/^\s*yes\s*$/i.test(b.text) && game.pending !== null && game.pending.pending_id === b.pending_id) {
        return stream(res, 'turn', b.text, confirmEvents('yes'));
      }
      return stream(res, 'turn', b.text, turnEvents(b.text));
    }
    if (method === 'POST' && sub === '/confirm') {
      const b = await body(req);
      requests.push({ route: 'confirm', body: b });
      if (game.pending === null || game.pending.pending_id !== b.pending_id)
        return error(res, 409, 'no_such_pending', 'that confirmation is not waiting any more');
      return stream(res, 'confirm', b.answer, confirmEvents(b.answer));
    }
    if (method === 'POST' && sub === '/save') {
      const name = '0123456789abcdef';
      saves = [
        { name, created_at: new Date().toISOString(), pack: chosenPack, setting: settingOf(chosenPack), status: game.outcome },
        ...saves.filter((s) => s.name !== name),
      ];
      return json(res, 200, { name });
    }
    return error(res, 405, 'method_not_allowed', 'method not allowed');
  } catch {
    return error(res, 500, 'internal', 'something went wrong');
  }
}).listen(PORT, '127.0.0.1', () => {
  console.log(`fake gumshoe api on http://127.0.0.1:${PORT}`);
});
