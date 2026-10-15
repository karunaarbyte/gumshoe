import { vi } from 'vitest';
import type { Api } from '../api/client';
import { ApiError } from '../api/errors';
import { readEvents } from '../api/sse';
import type { GameState, TurnEvent, TurnRecord } from '../api/types';
import { brief, healthOn, meta, states } from './fixtures';
import { sseText, streamOf } from './streams';

export function eventsOf(events: TurnEvent[]): AsyncGenerator<TurnEvent> {
  return readEvents(streamOf([sseText(events)]));
}

/** Events, then a dropped connection. */
export async function* droppedAfter(events: TurnEvent[]): AsyncGenerator<TurnEvent> {
  yield* events;
  throw new TypeError('network error');
}

export function apiError(code: string, status = 409, message = code): ApiError {
  return new ApiError(status, code, message);
}

/** An Api whose every method is a vi.fn with a sensible default. Override per test. */
export function fakeApi(init: { state?: GameState; turns?: TurnRecord[] } = {}) {
  const client = {
    health: vi.fn<Api['health']>(async () => healthOn),
    meta: vi.fn<Api['meta']>(async () => meta),
    games: vi.fn<Api['games']>(async () => []),
    saves: vi.fn<Api['saves']>(async () => []),
    createGame: vi.fn<Api['createGame']>(async () => ({ game: 'g1', brief, preset: 'standard' })),
    loadGame: vi.fn<Api['loadGame']>(async () => ({ game: 'g2', brief, preset: null })),
    state: vi.fn<Api['state']>(async () => init.state ?? states[0]!),
    turns: vi.fn<Api['turns']>(async () => init.turns ?? []),
    save: vi.fn<Api['save']>(async () => ({ name: '0123456789abcdef' })),
    deleteGame: vi.fn<Api['deleteGame']>(async () => undefined),
    decision: vi.fn<Api['decision']>(async (id: string) => {
      throw new ApiError(404, 'not_recorded_yet', `no ${id}`);
    }),
    turn: vi.fn<Api['turn']>(async () => eventsOf([{ kind: 'done', turn_ms: 1 }])),
    confirm: vi.fn<Api['confirm']>(async () => eventsOf([{ kind: 'done', turn_ms: 1 }])),
  };
  return client;
}

export type FakeApi = ReturnType<typeof fakeApi>;
