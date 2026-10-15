import { afterEach, describe, expect, test, vi } from 'vitest';
import { collect, errorResponse, jsonResponse, sseResponse } from '../test/streams';
import { api } from './client';
import { ApiError } from './errors';

function stubFetch(...responses: (Response | Error)[]) {
  const fetchMock = vi.fn<typeof fetch>();
  for (const r of responses) {
    if (r instanceof Error) fetchMock.mockRejectedValueOnce(r);
    else fetchMock.mockResolvedValueOnce(r);
  }
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api client', () => {
  test('reads JSON from a GET', async () => {
    stubFetch(jsonResponse({ presets: ['standard'], default_preset: 'standard', max_attempts: 3, max_turn_chars: 1000 }));
    await expect(api.meta()).resolves.toMatchObject({ max_turn_chars: 1000 });
  });

  test('a non-2xx body becomes ApiError(code, message)', async () => {
    stubFetch(errorResponse(404, 'unknown_game', 'no such game'));
    const error = await api.state('g1').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: 'unknown_game', message: 'no such game' });
  });

  test('a body that is not JSON becomes http_error', async () => {
    stubFetch(new Response('<html>bad gateway</html>', { status: 502 }));
    await expect(api.health()).rejects.toMatchObject({ status: 502, code: 'http_error' });
  });

  test('a network failure becomes the network code', async () => {
    stubFetch(new TypeError('Failed to fetch'));
    await expect(api.games()).rejects.toMatchObject({ status: 0, code: 'network' });
  });

  test('creates a game with a seed and an optional preset', async () => {
    const fetchMock = stubFetch(jsonResponse({ game: 'g1', brief: {}, preset: 'short' }));
    await api.createGame(7, 'short');
    expect(fetchMock).toHaveBeenCalledWith('/api/games', expect.objectContaining({ method: 'POST', body: '{"seed":7,"preset":"short"}' }));
  });

  test('a turn posts its body and streams events', async () => {
    const fetchMock = stubFetch(sseResponse([{ kind: 'done', turn_ms: 5 }]));
    const events = await collect(await api.turn('g1', { text: 'hello' }));
    expect(events).toEqual([{ kind: 'done', turn_ms: 5 }]);
    expect(fetchMock).toHaveBeenCalledWith('/api/games/g1/turn', expect.objectContaining({ method: 'POST', body: '{"text":"hello"}' }));
  });

  test('a 409 before the stream starts throws, it does not stream', async () => {
    stubFetch(errorResponse(409, 'turn_in_progress'));
    await expect(api.turn('g1', { text: 'hi' })).rejects.toMatchObject({ code: 'turn_in_progress' });
  });

  test('confirm posts pending_id and answer', async () => {
    const fetchMock = stubFetch(sseResponse([{ kind: 'cancelled' }, { kind: 'done', turn_ms: 1 }]));
    await collect(await api.confirm('g1', { pending_id: 'p1', answer: 'no' }));
    expect(fetchMock).toHaveBeenCalledWith('/api/games/g1/confirm', expect.objectContaining({ body: '{"pending_id":"p1","answer":"no"}' }));
  });

  test('delete answers nothing on 204', async () => {
    stubFetch(new Response(null, { status: 204 }));
    await expect(api.deleteGame('g1')).resolves.toBeUndefined();
  });

  test('game ids are URL-encoded', async () => {
    const fetchMock = stubFetch(jsonResponse([]));
    await api.turns('a/b');
    expect(fetchMock).toHaveBeenCalledWith('/api/games/a%2Fb/turns', expect.anything());
  });
});
