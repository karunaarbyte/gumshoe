import { describe, expect, test } from 'vitest';
import type { TurnEvent } from '../api/types';
import { confirmFirst, confirmSecond, reveal, states, transcript } from '../test/fixtures';
import { type GameAction, type GameView, emptyView } from './model';
import { gameReducer } from './reducer';
import { rebuild, recordActions } from './rebuild';

const fold = (actions: GameAction[], from: GameView = emptyView('g1')) => actions.reduce(gameReducer, from);
const start: GameAction = { type: 'turn_started', kind: 'turn', text: 'hi', ts: '2026-10-15T10:00:00.000+00:00' };
const ev = (event: TurnEvent): GameAction => ({ type: 'event', event });

describe('gameReducer, per event kind', () => {
  test('turn_started adds a player slip and marks the turn running', () => {
    const view = fold([start]);
    expect(view.status).toBe('running');
    expect(view.messages).toEqual([{ id: 'm0', turn: 0, kind: 'player', text: 'hi', via: 'turn' }]);
    expect(view.turns).toHaveLength(1);
  });

  test('intent and post_check are kept for the trace only, with their decision ids', () => {
    const view = fold([
      start,
      ev({ kind: 'intent', decision_id: 'd1', intent: 'search', target: null, confidence: 0.9 }),
      ev({ kind: 'post_check', decision_id: 'd2', contradicts_says: null, claims_guilt_or_blames_other: 0.1, failed: false }),
    ]);
    expect(view.messages.map((m) => m.kind)).toEqual(['player']);
    expect(view.turns[0]?.decisionIds).toEqual(['d1', 'd2']);
    expect(view.turns[0]?.events).toHaveLength(2);
  });

  test('a decision id seen twice in one turn is listed once', () => {
    const view = fold([
      start,
      ev({ kind: 'clarify', reason: 'accusation', text: '?', decision_id: 'd1', problems: [] }),
      ev({ ...confirmFirst, decision_id: 'd1' }),
    ]);
    expect(view.turns[0]?.decisionIds).toEqual(['d1']);
  });

  test('reply and clarify become chat messages', () => {
    const view = fold([start, ...transcript[0]!.events.map(ev), ev({ kind: 'clarify', reason: 'low_confidence', text: 'Say again?', decision_id: null, problems: [] })]);
    expect(view.messages.map((m) => m.kind)).toEqual(['player', 'reply', 'clarify']);
  });

  test('tool_result pairs with its tool_call; a failure keeps ok false', () => {
    const view = fold([start, ...transcript[3]!.events.map(ev)]);
    const tool = view.messages.find((m) => m.kind === 'tool');
    expect(tool).toMatchObject({ call: { tool: 'interrogate' }, result: { ok: false, code: 'unknown_handle' } });
  });

  test('a tool_result without a call still shows', () => {
    const view = fold([start, ev({ kind: 'tool_result', tool: 'search', ok: true, code: null, message: null, data: null })]);
    expect(view.messages[1]).toMatchObject({ kind: 'tool', call: { tool: 'search', args: {} } });
  });

  test('confirm sets the pending confirmation and opens a card', () => {
    const view = fold([start, ev(confirmFirst)]);
    expect(view.pending).toEqual({ pending_id: 'p-first', kind: 'accuse', text: confirmFirst.text, warnings: confirmFirst.warnings });
    expect(view.messages[1]).toMatchObject({ kind: 'confirm', state: 'open' });
  });

  test('a second confirm replaces the first', () => {
    const view = fold([start, ev(confirmFirst), ev(confirmSecond)]);
    expect(view.messages.filter((m) => m.kind === 'confirm').map((m) => m.kind === 'confirm' && m.state)).toEqual(['replaced', 'open']);
    expect(view.pending?.pending_id).toBe('p-second');
  });

  test('cancelled strikes the open card and clears pending', () => {
    const view = fold([start, ev(confirmFirst), ev({ kind: 'cancelled' })]);
    expect(view.pending).toBeNull();
    expect(view.messages[1]).toMatchObject({ kind: 'confirm', state: 'cancelled' });
  });

  test('cancelled with nothing open changes no card', () => {
    const view = fold([start, ev({ kind: 'cancelled' })]);
    expect(view.messages).toHaveLength(1);
  });

  test('an accuse or give_up tool call answers the open card', () => {
    const view = fold([start, ev(confirmFirst), { type: 'turn_started', kind: 'confirm', text: 'yes', ts: 't' }, ev({ kind: 'tool_call', tool: 'accuse', args: {} })]);
    expect(view.pending).toBeNull();
    expect(view.messages[1]).toMatchObject({ kind: 'confirm', state: 'answered' });
  });

  test('game_over sets outcome and reveal and adds a message', () => {
    const view = fold([start, ev({ kind: 'game_over', outcome: 'gave_up', reveal })]);
    expect(view.outcome).toBe('gave_up');
    expect(view.reveal).toEqual(reveal);
    expect(view.messages[1]).toMatchObject({ kind: 'game_over' });
  });

  test('done completes the turn and frees the input', () => {
    const view = fold([start, ev({ kind: 'done', turn_ms: 42 })]);
    expect(view.status).toBe('idle');
    expect(view.turns[0]).toMatchObject({ complete: true, turnMs: 42 });
  });

  test('a stream that ends without done marks the turn lost', () => {
    expect(fold([start, { type: 'stream_ended', sawDone: false }]).status).toBe('lost');
    expect(fold([start, ev({ kind: 'done', turn_ms: 1 }), { type: 'stream_ended', sawDone: true }]).status).toBe('idle');
  });

  test('server_state is the truth for pending, outcome and reveal, and closes stale cards', () => {
    const view = fold([start, ev(confirmFirst), { type: 'server_state', state: states[0]! }]);
    expect(view.pending).toBeNull();
    expect(view.messages[1]).toMatchObject({ kind: 'confirm', state: 'closed' });
    expect(view.state).toBe(states[0]);
  });

  test('server_state keeps the card it still holds open', () => {
    const view = fold([start, ev(confirmFirst), { type: 'server_state', state: states[6]! }]);
    expect(view.messages[1]).toMatchObject({ kind: 'confirm', state: 'open' });
  });
});

describe('reload equals live', () => {
  /** What the turn hook dispatches: the turn, its events, the end, then the fresh state.
   * The live path passes the record's ts only so the two folds compare; the real hook uses a
   * client clock until a reload replaces it (TurnView.ts is advisory).
   * Every fixture server_state agrees with the event fold. One accepted drift: a pending the
   * server drops without a `cancelled` event reads `closed` live but `replaced`/`cancelled`
   * after a reload (a visual label only; neither is answerable). */
  function live(upTo: number): GameView {
    // a desk opens with the state of the new game, then plays turns
    let view = fold([{ type: 'server_state', state: states[0]! }]);
    transcript.slice(0, upTo).forEach((record, i) => {
      view = fold([
        { type: 'turn_started', kind: record.kind, text: record.text, ts: record.ts },
        ...record.events.map(ev),
        { type: 'stream_ended', sawDone: true },
        { type: 'server_state', state: states[i + 1]! },
      ], view);
    });
    return view;
  }

  test.each(Array.from({ length: transcript.length + 1 }, (_, k) => k))(
    'after %i turns the reloaded view equals the live view',
    (k) => {
      expect(rebuild('g1', states[k]!, transcript.slice(0, k))).toEqual(live(k));
    },
  );

  test('the full game ends won with the reveal and no pending', () => {
    const view = rebuild('g1', states[10]!, transcript);
    expect(view).toMatchObject({ outcome: 'won', reveal, pending: null, status: 'idle' });
    const cards = view.messages.flatMap((m) => (m.kind === 'confirm' ? [m.state] : []));
    expect(cards).toEqual(['cancelled', 'answered']);
  });

  test('a reload mid-turn shows the turn running remotely', () => {
    const running = { ...transcript[1]!, complete: false, events: transcript[1]!.events.slice(0, 2) };
    const view = rebuild('g1', states[1]!, [transcript[0]!, running]);
    expect(view.status).toBe('remote');
    expect(view.turns[1]?.complete).toBe(false);
  });

  test('a complete record without done (a turn that died) is closed', () => {
    const died = { ...transcript[1]!, events: transcript[1]!.events.slice(0, 2) };
    expect(recordActions(died).at(-1)).toEqual({ type: 'turn_closed' });
    expect(rebuild('g1', states[2]!, [died]).status).toBe('idle');
  });

  test('a pending whose card fell outside the turns window shows no open card', () => {
    const view = rebuild('g1', states[6]!, transcript.slice(0, 1));
    expect(view.pending?.pending_id).toBe('p-first');
    expect(view.messages.some((m) => m.kind === 'confirm' && m.state === 'open')).toBe(false);
  });
});
