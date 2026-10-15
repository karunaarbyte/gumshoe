import { describe, expect, test } from 'vitest';
import { ApiError } from '../api/errors';
import { ENDED_MESSAGE, UNREACHABLE_MESSAGE, classify } from './errorPolicy';
import { parseRoute, routeHash } from './route';

describe('route', () => {
  test('a game hash opens the desk; anything else is the title', () => {
    expect(parseRoute('#/game/abc123')).toEqual({ name: 'desk', game: 'abc123' });
    expect(parseRoute('')).toEqual({ name: 'title' });
    expect(parseRoute('#/game/')).toEqual({ name: 'title' });
    expect(parseRoute('#/game/%E0%A4%A')).toEqual({ name: 'title' });
  });

  test('round trip', () => {
    expect(parseRoute(routeHash({ name: 'desk', game: 'a b' }))).toEqual({ name: 'desk', game: 'a b' });
  });
});

describe('classify', () => {
  const e = (code: string, message = 'm') => new ApiError(400, code, message);
  test.each([
    ['unavailable', { kind: 'off', message: 'm' }],
    ['unknown_game', { kind: 'ended' }],
    ['turn_in_progress', { kind: 'notice', message: 'A turn is already running for this game.' }],
    ['network', { kind: 'toast', message: UNREACHABLE_MESSAGE }],
    ['too_many_games', { kind: 'toast', message: 'm' }],
    ['bad_save', { kind: 'toast', message: 'm' }],
    ['bad_argument', { kind: 'toast', message: 'm' }],
    ['bad_request', { kind: 'toast', message: 'm' }],
    ['internal', { kind: 'toast', message: 'm' }],
  ])('%s', (code, action) => {
    expect(classify(e(code))).toEqual(action);
  });

  test('the ended message', () => {
    expect(ENDED_MESSAGE).toMatch(/server may have restarted/);
  });
});
