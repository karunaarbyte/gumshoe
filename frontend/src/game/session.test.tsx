import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { confirmFirst, reveal, states, transcript } from '../test/fixtures';
import { apiError, droppedAfter, eventsOf, fakeApi } from '../test/fakeApi';
import { CONNECTION_LOST_NOTICE, PENDING_GONE_NOTICE, TURN_RUNNING_NOTICE, useGameSession } from './session';

function setup(client = fakeApi()) {
  const handlers = { onError: vi.fn(), onNotice: vi.fn() };
  const hook = renderHook(() => useGameSession('g1', handlers, { client, pollMs: 5, now: () => 'NOW' }));
  return { client, handlers, hook };
}

const waitingState = states[6]!; // a confirmation waits: p-first

describe('useGameSession', () => {
  test('loads state and transcript on mount', async () => {
    const { hook } = setup(fakeApi({ state: states[3], turns: transcript.slice(0, 3) }));
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    expect(hook.result.current.view.turns).toHaveLength(3);
    expect(hook.result.current.view.state).toEqual(states[3]);
  });

  test('a turn streams events, then refreshes state', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(eventsOf(transcript[1]!.events));
    client.state.mockResolvedValueOnce(states[0]!).mockResolvedValueOnce(states[2]!);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('search the long gallery'));
    expect(client.turn).toHaveBeenCalledWith('g1', { text: 'search the long gallery' }, expect.any(AbortSignal));
    expect(hook.result.current.view.messages.map((m) => m.kind)).toEqual(['player', 'tool', 'reply']);
    expect(hook.result.current.view.state).toEqual(states[2]);
    expect(hook.result.current.busy).toBe(false);
  });

  test('without a waiting confirmation a typed yes carries no pending_id', async () => {
    const { client, hook } = setup();
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('yes'));
    expect(client.turn).toHaveBeenCalledWith('g1', { text: 'yes' }, expect.any(AbortSignal));
  });

  test('with a waiting confirmation a typed yes carries its pending_id', async () => {
    const { client, hook } = setup(fakeApi({ state: waitingState, turns: transcript.slice(0, 6) }));
    await waitFor(() => expect(hook.result.current.view.pending?.pending_id).toBe('p-first'));
    await act(() => hook.result.current.send('  yes  '));
    expect(client.turn).toHaveBeenCalledWith('g1', { text: 'yes', pending_id: 'p-first' }, expect.any(AbortSignal));
  });

  test('the Yes button posts confirm with the waiting id', async () => {
    const client = fakeApi({ state: waitingState, turns: transcript.slice(0, 6) });
    client.confirm.mockResolvedValueOnce(eventsOf(transcript[9]!.events));
    client.state.mockResolvedValueOnce(waitingState).mockResolvedValueOnce(states[10]!);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.view.pending).not.toBeNull());
    await act(() => hook.result.current.answer('yes'));
    expect(client.confirm).toHaveBeenCalledWith('g1', { pending_id: 'p-first', answer: 'yes' }, expect.any(AbortSignal));
    expect(hook.result.current.view).toMatchObject({ outcome: 'won', reveal, pending: null });
  });

  test('answer does nothing when no confirmation waits', async () => {
    const { client, hook } = setup();
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.answer('yes'));
    expect(client.confirm).not.toHaveBeenCalled();
  });

  test('a double click sends one confirm', async () => {
    const { client, hook } = setup(fakeApi({ state: waitingState, turns: transcript.slice(0, 6) }));
    await waitFor(() => expect(hook.result.current.view.pending).not.toBeNull());
    await act(async () => {
      await Promise.all([hook.result.current.answer('yes'), hook.result.current.answer('yes')]);
    });
    expect(client.confirm).toHaveBeenCalledTimes(1);
  });

  test('nothing is sent once the game is over', async () => {
    const { client, hook } = setup(fakeApi({ state: states[10], turns: transcript }));
    await waitFor(() => expect(hook.result.current.view.outcome).toBe('won'));
    await act(() => hook.result.current.send('hello'));
    expect(client.turn).not.toHaveBeenCalled();
  });

  test('409 turn_in_progress: a notice, then poll until the turn ends', async () => {
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError('turn_in_progress'));
    const running = { ...transcript[0]!, complete: false, events: [] };
    client.turns.mockResolvedValueOnce([]).mockResolvedValueOnce([running]).mockResolvedValue([transcript[0]!]);
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    expect(handlers.onNotice).toHaveBeenCalledWith(TURN_RUNNING_NOTICE);
    expect(hook.result.current.busy).toBe(true);
    await waitFor(() => expect(hook.result.current.view.turns[0]?.complete).toBe(true));
    expect(hook.result.current.busy).toBe(false);
  });

  test('a stream that drops without done reloads state and transcript', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(droppedAfter(transcript[1]!.events.slice(0, 2)));
    client.turns.mockResolvedValueOnce([]).mockResolvedValue([transcript[1]!]);
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('search the long gallery'));
    expect(handlers.onNotice).toHaveBeenCalledWith(CONNECTION_LOST_NOTICE);
    expect(client.turns).toHaveBeenCalledTimes(2);
    expect(hook.result.current.view.turns[0]?.complete).toBe(true);
    expect(hook.result.current.busy).toBe(false);
  });

  test('an empty stream (no events, no done) takes the reload path', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(eventsOf([]));
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    expect(handlers.onNotice).toHaveBeenCalledWith(CONNECTION_LOST_NOTICE);
    expect(client.state).toHaveBeenCalledTimes(2);
  });

  test('no_such_pending reloads so the stale card closes', async () => {
    const client = fakeApi({ state: waitingState, turns: transcript.slice(0, 6) });
    client.confirm.mockRejectedValueOnce(apiError('no_such_pending'));
    client.state.mockResolvedValueOnce(waitingState).mockResolvedValue(states[8]!);
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.view.pending).not.toBeNull());
    await act(() => hook.result.current.answer('yes'));
    expect(hook.result.current.view.pending).toBeNull();
    expect(handlers.onNotice).toHaveBeenCalledWith(PENDING_GONE_NOTICE);
  });

  test('other errors go to onError', async () => {
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError('unknown_game', 404));
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    expect(handlers.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'unknown_game' }));
  });

  test('a network failure on the first load gives the connection-lost notice, not a crash', async () => {
    const client = fakeApi();
    client.state.mockRejectedValueOnce(new TypeError('network error'));
    const { handlers } = setup(client);
    await waitFor(() => expect(handlers.onNotice).toHaveBeenCalledWith(CONNECTION_LOST_NOTICE));
  });

  test('a failing first load goes to onError', async () => {
    const client = fakeApi();
    client.state.mockRejectedValueOnce(apiError('unavailable', 503));
    const { handlers } = setup(client);
    await waitFor(() => expect(handlers.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'unavailable' })));
  });

  test('confirm events in a live turn open the pending', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(eventsOf([confirmFirst, { kind: 'done', turn_ms: 1 }]));
    client.state.mockResolvedValueOnce(states[0]!).mockResolvedValueOnce(waitingState);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('accuse the butler'));
    expect(hook.result.current.view.pending?.pending_id).toBe('p-first');
  });

  test('nothing is reported after unmount, even when the abort surfaces as a network ApiError', async () => {
    const client = fakeApi();
    let fail: (e: unknown) => void = () => undefined;
    client.turn.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject; }));
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    let sent: Promise<void> = Promise.resolve();
    act(() => { sent = hook.result.current.send('hello'); });
    hook.unmount();
    fail(apiError('network', 0));
    await sent;
    expect(handlers.onError).not.toHaveBeenCalled();
    expect(handlers.onNotice).not.toHaveBeenCalled();
  });

  test('a lost stream whose first reload fails keeps retrying until it recovers', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(droppedAfter(transcript[1]!.events.slice(0, 2)));
    client.state.mockResolvedValueOnce(states[0]!).mockRejectedValueOnce(apiError('unavailable', 503));
    client.turns.mockResolvedValueOnce([]).mockResolvedValue([transcript[1]!]);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('search the long gallery'));
    await waitFor(() => expect(hook.result.current.view.status).toBe('idle'));
    expect(hook.result.current.busy).toBe(false);
  });

  test('a remote poll that fails once keeps polling until the turn completes', async () => {
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError('turn_in_progress'));
    const running = { ...transcript[0]!, complete: false, events: [] };
    client.turns.mockResolvedValueOnce([]).mockRejectedValueOnce(apiError('unavailable', 503))
      .mockRejectedValueOnce(new TypeError('network error')).mockResolvedValueOnce([running])
      .mockResolvedValue([transcript[0]!]);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    await waitFor(() => expect(hook.result.current.view.turns[0]?.complete).toBe(true));
    expect(hook.result.current.busy).toBe(false);
  });

  test('a non-API failure during the connection-lost reload does not reject send', async () => {
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(droppedAfter([]));
    client.state.mockResolvedValueOnce(states[0]!).mockRejectedValueOnce(new SyntaxError('bad json'));
    const { handlers, hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    expect(handlers.onNotice).toHaveBeenCalledWith(CONNECTION_LOST_NOTICE);
  });

  test('send before the first load finishes sends nothing', async () => {
    const { client, hook } = setup();
    await act(() => hook.result.current.send('hello'));
    expect(client.turn).not.toHaveBeenCalled();
  });

  test('a Yes press racing a typed send makes exactly one request', async () => {
    const { client, hook } = setup(fakeApi({ state: waitingState, turns: transcript.slice(0, 6) }));
    await waitFor(() => expect(hook.result.current.view.pending).not.toBeNull());
    await act(async () => {
      await Promise.all([hook.result.current.answer('yes'), hook.result.current.send('yes')]);
    });
    expect(client.confirm.mock.calls.length + client.turn.mock.calls.length).toBe(1);
  });

  test('send is refused while another turn runs remotely', async () => {
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError('turn_in_progress'));
    client.turns.mockResolvedValueOnce([]).mockResolvedValue([{ ...transcript[0]!, complete: false, events: [] }]);
    const { hook } = setup(client);
    await waitFor(() => expect(hook.result.current.ready).toBe(true));
    await act(() => hook.result.current.send('hello'));
    await act(() => hook.result.current.send('again'));
    expect(client.turn).toHaveBeenCalledTimes(1);
  });
});
