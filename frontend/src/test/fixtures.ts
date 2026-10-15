import type {
  ConfirmEvent,
  DecisionView,
  GameState,
  Health,
  Meta,
  PlayerCaseView,
  Reveal,
  TurnEvent,
  TurnRecord,
} from '../api/types';

export const meta: Meta = {
  presets: ['short', 'standard'],
  default_preset: 'standard',
  max_attempts: 3,
  max_turn_chars: 1000,
};

export const healthOn: Health = {
  status: 'ok',
  game: 'on',
  reason: null,
  primary: 'jev',
  shadow: 'nimble',
  persona_models: { default: 'ministral-3:14b', dramatic: 'gemma4:12b' },
};

export const healthOff: Health = { ...healthOn, game: 'off', reason: 'the decider is not configured: JEV_API_KEY is missing' };

export const brief: PlayerCaseView = {
  intro: 'Lord Ashby lies dead in the long gallery.',
  suspects: [
    { number: 1, handle: 's1', name: 'Mr Grey the butler', description: 'Stiff and correct.', locked: false },
    { number: 2, handle: 's2', name: 'Mrs Pike the cook', description: 'Floury hands.', locked: false },
    { number: 3, handle: 's3', name: 'Dr Wren the physician', description: 'Arrived late.', locked: true },
  ],
  locations: [
    { number: 1, handle: 'l1', name: 'Long gallery', description: 'Portraits and a body.', locked: false },
    { number: 2, handle: 'l2', name: 'Wine cellar', description: 'Dark and damp.', locked: true },
  ],
  record_kinds: [
    { key: 'letters', label: 'Letters' },
    { key: 'ledger', label: 'Household ledger' },
  ],
  attempts_left: 3,
  status: 'playing',
};

export const reveal: Reveal = {
  culprit: 'Mr Grey the butler',
  method: 'poisoned port',
  motive: 'an unpaid inheritance',
  secret: 'he is the late lord’s son',
};

export const decisionIds = {
  greet: 'd-greet',
  search: 'd-search',
  ask: 'd-ask',
  check: 'd-check',
  accuse1: 'd-acc1',
  accuse2: 'd-acc2',
  accuse3: 'd-acc3',
  hmm: 'd-hmm',
  no: 'd-no',
} as const;

const done = (turn_ms: number): TurnEvent => ({ kind: 'done', turn_ms });
const intent = (decision_id: string, name: string, target: string | null = null): TurnEvent => ({
  kind: 'intent',
  decision_id,
  intent: name,
  target,
  confidence: 0.93,
});

export const confirmFirst: ConfirmEvent = {
  kind: 'confirm',
  pending: 'accuse',
  pending_id: 'p-first',
  text: 'Accuse Mr Grey the butler, by poisoned port, for an unpaid inheritance?',
  warnings: ['You hold a fact that points away from Mr Grey.'],
  decision_id: decisionIds.accuse2,
};

export const confirmSecond: ConfirmEvent = {
  ...confirmFirst,
  pending_id: 'p-second',
  warnings: [],
  decision_id: decisionIds.accuse3,
};

/** A whole game as `/turns` returns it: ten turns, from hello to a won accusation. */
export const transcript: TurnRecord[] = [
  {
    turn_id: 't0', kind: 'turn', text: 'hello', ts: '2026-10-15T10:00:00.000+00:00', complete: true,
    events: [
      intent(decisionIds.greet, 'meta'),
      { kind: 'reply', speaker: null, text: 'Ask about a suspect, search a place, or accuse.', source: 'help', degraded: false, violations: [], model: null, drafts: 0, latency_ms: null },
      done(410),
    ],
  },
  {
    turn_id: 't1', kind: 'turn', text: 'search the long gallery', ts: '2026-10-15T10:00:10.000+00:00', complete: true,
    events: [
      intent(decisionIds.search, 'search', 'l1'),
      { kind: 'tool_call', tool: 'search', args: { game: 'g1', location: 'l1' } },
      { kind: 'tool_result', tool: 'search', ok: true, code: null, message: null, data: { kind: 'search', label: 'Long gallery', status: 'ok' } },
      { kind: 'reply', speaker: null, text: 'You find a stained glass by the body.', source: 'draft', degraded: false, violations: [], model: 'ministral-3:14b', drafts: 1, latency_ms: 640 },
      done(1500),
    ],
  },
  {
    turn_id: 't2', kind: 'turn', text: 'ask Mr Grey where he was', ts: '2026-10-15T10:00:20.000+00:00', complete: true,
    events: [
      intent(decisionIds.ask, 'interrogate', 's1'),
      { kind: 'tool_call', tool: 'interrogate', args: { game: 'g1', suspect: 's1' } },
      { kind: 'tool_result', tool: 'interrogate', ok: true, code: null, message: null, data: { kind: 'interrogate', label: 'Mr Grey the butler', status: 'ok' } },
      { kind: 'reply', speaker: 'Mr Grey the butler', text: 'In the pantry, sir, all evening.', source: 'canned', degraded: true, violations: ['claims_guilt'], model: 'gemma4:12b', drafts: 2, latency_ms: 2100 },
      { kind: 'post_check', decision_id: decisionIds.check, contradicts_says: 0.1, claims_guilt_or_blames_other: 0.7, failed: true },
      done(3200),
    ],
  },
  {
    turn_id: 't3', kind: 'turn', text: 'ask Dr Wren', ts: '2026-10-15T10:00:30.000+00:00', complete: true,
    events: [
      intent(decisionIds.ask + '-2', 'interrogate', 's3'),
      { kind: 'tool_call', tool: 'interrogate', args: { game: 'g1', suspect: 's3' } },
      { kind: 'tool_result', tool: 'interrogate', ok: false, code: 'unknown_handle', message: 'no such suspect', data: null },
      { kind: 'reply', speaker: 'Dr Wren the physician', text: 'Dr Wren is not available yet.', source: 'unreachable', degraded: false, violations: [], model: null, drafts: 0, latency_ms: null },
      done(700),
    ],
  },
  {
    turn_id: 't4', kind: 'turn', text: 'I accuse the butler', ts: '2026-10-15T10:00:40.000+00:00', complete: true,
    events: [
      intent(decisionIds.accuse1, 'accuse'),
      {
        kind: 'clarify', reason: 'accusation', text: 'How, and why?', decision_id: decisionIds.accuse1,
        problems: [
          { axis: 'how', reason: 'unclear', options: [{ handle: 'm1', name: 'poisoned port' }, { handle: 'm2', name: 'a candlestick' }] },
          { axis: 'why', reason: 'unclear', options: [{ handle: 'w1', name: 'an unpaid inheritance' }] },
        ],
      },
      done(900),
    ],
  },
  {
    turn_id: 't5', kind: 'turn', text: 'poisoned port, for an unpaid inheritance', ts: '2026-10-15T10:00:50.000+00:00', complete: true,
    events: [intent(decisionIds.accuse2, 'accuse'), confirmFirst, done(1100)],
  },
  {
    turn_id: 't6', kind: 'turn', text: 'hmm', ts: '2026-10-15T10:01:00.000+00:00', complete: true,
    events: [
      intent(decisionIds.hmm, 'other'),
      { kind: 'clarify', reason: 'pending', text: `Still want to go ahead? ${confirmFirst.text}`, decision_id: null, problems: [] },
      done(600),
    ],
  },
  {
    turn_id: 't7', kind: 'turn', text: 'no', ts: '2026-10-15T10:01:10.000+00:00', complete: true,
    events: [intent(decisionIds.no, 'other'), { kind: 'cancelled' }, done(500)],
  },
  {
    turn_id: 't8', kind: 'turn', text: 'accuse Mr Grey, poisoned port, unpaid inheritance', ts: '2026-10-15T10:01:20.000+00:00', complete: true,
    events: [intent(decisionIds.accuse3, 'accuse'), confirmSecond, done(1000)],
  },
  {
    turn_id: 't9', kind: 'confirm', text: 'yes', ts: '2026-10-15T10:01:30.000+00:00', complete: true,
    events: [
      { kind: 'tool_call', tool: 'accuse', args: { game: 'g1', who: 's1', how: 'm1', why: 'w1', confirmed: true } },
      { kind: 'tool_result', tool: 'accuse', ok: true, code: null, message: null, data: { status: 'resolved', correct: 3 } },
      { kind: 'game_over', outcome: 'won', reveal },
      done(1300),
    ],
  },
];

const notebookEmpty = { sections: [], contradictions: [] };
const notebookFull = {
  sections: [
    {
      source: 'Long gallery',
      facts: [{ handle: 'f1', text: 'A stained glass lies by the body.', speaker: null, relates_to: ['Mr Grey the butler'], contradicted: false }],
    },
    {
      source: 'Mr Grey the butler',
      facts: [{ handle: 'f2', text: 'He was in the pantry all evening.', speaker: 'Mr Grey the butler', relates_to: [], contradicted: true }],
    },
    {
      source: 'Letters',
      facts: [{ handle: 'f3', text: 'The cook saw Grey in the gallery at nine.', speaker: null, relates_to: ['Mr Grey the butler', 'Mrs Pike the cook'], contradicted: false }],
    },
  ],
  contradictions: [{ lie: 'f2', exposer: 'f3', text: 'Grey says pantry; the cook saw him in the gallery.' }],
};

function stateAfter(turns: number): GameState {
  const pending =
    turns >= 6 && turns <= 7
      ? { pending_id: confirmFirst.pending_id, kind: 'accuse' as const, text: confirmFirst.text, warnings: confirmFirst.warnings }
      : turns === 9
        ? { pending_id: confirmSecond.pending_id, kind: 'accuse' as const, text: confirmSecond.text, warnings: [] }
        : null;
  const over = turns >= 10;
  return {
    brief: { ...brief, status: over ? 'won' : 'playing' },
    notebook: turns >= 2 ? notebookFull : notebookEmpty,
    outcome: over ? 'won' : 'playing',
    pending,
    reveal: over ? reveal : null,
    preset: 'standard',
  };
}

/** `states[k]` is `GET /api/games/g1` after the first k turns of `transcript`. */
export const states: GameState[] = Array.from({ length: transcript.length + 1 }, (_, k) => stateAfter(k));

export function decision(id: string, verdicts: [string, string] = ['search', 'search']): DecisionView {
  return {
    decision_id: id,
    node: 'understand',
    ts: '2026-10-15T10:00:10.100+00:00',
    fallback: false,
    state_preview: 'player: search the long gallery',
    calls: [
      { backend: 'jev', role: 'primary', used: true, cold: false, latency_ms: 120, error: null, input_tokens: 900, output_tokens: 12, est_cost_usd: 0.0004, answers: { intent: { verdict: verdicts[0], confidence: 0.93 }, confirms_pending: { verdict: 'no', confidence: 0.1 } } },
      { backend: 'nimble', role: 'shadow', used: false, cold: true, latency_ms: 480, error: null, input_tokens: 950, output_tokens: 15, est_cost_usd: 0.0001, answers: { intent: { verdict: verdicts[1], confidence: 0.71 }, confirms_pending: { verdict: 'no', confidence: 0.2 } } },
    ],
  };
}
