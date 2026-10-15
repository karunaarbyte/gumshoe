import type { GameState, TurnRecord } from '../api/types';
import { type GameAction, type GameView, emptyView } from './model';
import { gameReducer } from './reducer';

/** The actions a stored turn stands for: the same ones the live path dispatches. */
export function recordActions(record: TurnRecord): GameAction[] {
  const actions: GameAction[] = [
    { type: 'turn_started', kind: record.kind, text: record.text, ts: record.ts },
    ...record.events.map((event): GameAction => ({ type: 'event', event })),
  ];
  const sawDone = record.events.some((e) => e.kind === 'done');
  if (record.complete && !sawDone) actions.push({ type: 'turn_closed' });
  return actions;
}

/** The view a reloaded page draws: the transcript folded, then the server's state on top. */
export function rebuild(game: string, state: GameState, records: TurnRecord[]): GameView {
  const actions = records.flatMap(recordActions);
  actions.push({ type: 'server_state', state });
  const last = records[records.length - 1];
  if (last !== undefined && !last.complete) actions.push({ type: 'remote_running' });
  return actions.reduce(gameReducer, emptyView(game));
}
