import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { App, defaultQueryClient } from './App';
import { ApiError } from './api/errors';
import { gameKey, loadBoard, saveKey, storeBoard } from './board/storage';
import { confirmFirst, healthOff, healthOn, reveal, states, transcript } from './test/fixtures';
import { apiError, droppedAfter, eventsOf, fakeApi } from './test/fakeApi';
import { preferReducedMotion, testQueryClient } from './test/render';

function renderApp(client = fakeApi()) {
  render(<App client={client} queryClient={testQueryClient()} session={{ pollMs: 5 }} />);
  return client;
}

beforeEach(() => preferReducedMotion(true));
afterEach(() => {
  window.location.hash = '';
});

describe('App', () => {
  test('the title screen by default', async () => {
    renderApp();
    expect(await screen.findByRole('heading', { name: 'GUMSHOE' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New case' })).toBeInTheDocument();
  });

  test('a new case opens the desk and puts its id in the URL', async () => {
    renderApp();
    await waitFor(() => expect(screen.getByRole('button', { name: 'New case' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'New case' }));
    expect(await screen.findByRole('navigation', { name: 'Notebook' })).toBeInTheDocument();
    expect(window.location.hash).toBe('#/game/g1');
  });

  test('a page reload on #/game/<id> rebuilds the desk with the waiting confirmation', async () => {
    window.location.hash = '#/game/g1';
    renderApp(fakeApi({ state: states[6], turns: transcript.slice(0, 6) }));
    const card = await screen.findByRole('region', { name: 'Accusation confirmation' });
    expect(within(card).getByRole('button', { name: /^Yes/ })).toBeEnabled();
  });

  test('typed yes while a confirmation waits sends its pending_id; the Yes button posts confirm', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi({ state: states[6], turns: transcript.slice(0, 6) });
    client.turn.mockResolvedValueOnce(eventsOf([{ kind: 'intent', decision_id: 'x', intent: 'other', target: null, confidence: 0.4 }, { kind: 'clarify', reason: 'pending', text: `Still want to go ahead? ${confirmFirst.text}`, decision_id: null, problems: [] }, { kind: 'done', turn_ms: 1 }]));
    renderApp(client);
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await userEvent.type(box, 'yes{Enter}');
    await waitFor(() => expect(client.turn).toHaveBeenCalledWith('g1', { text: 'yes', pending_id: 'p-first' }, expect.any(AbortSignal)));
    const card = await screen.findByRole('region', { name: 'Accusation confirmation' });
    await waitFor(() => expect(within(card).getByRole('button', { name: /^Yes/ })).toBeEnabled());
    await userEvent.click(within(card).getByRole('button', { name: /^Yes/ }));
    await waitFor(() => expect(client.confirm).toHaveBeenCalledWith('g1', { pending_id: 'p-first', answer: 'yes' }, expect.any(AbortSignal)));
  });

  test('No cancels through confirm with answer no', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi({ state: states[6], turns: transcript.slice(0, 6) });
    client.confirm.mockResolvedValueOnce(eventsOf([{ kind: 'cancelled' }, { kind: 'done', turn_ms: 1 }]));
    client.state.mockResolvedValueOnce(states[6]!).mockResolvedValue(states[8]!);
    renderApp(client);
    const card = await screen.findByRole('region', { name: 'Accusation confirmation' });
    await userEvent.click(within(card).getByRole('button', { name: /^No/ }));
    await waitFor(() => expect(card).toHaveAttribute('data-state', 'cancelled'));
    expect(client.confirm).toHaveBeenCalledWith('g1', { pending_id: 'p-first', answer: 'no' }, expect.any(AbortSignal));
  });

  test('the Accuse button prefills the input without sending anything', async () => {
    window.location.hash = '#/game/g1';
    const client = renderApp();
    await userEvent.click(await screen.findByRole('button', { name: 'Accuse' }));
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('I accuse ');
    expect(client.turn).not.toHaveBeenCalled();
  });

  test('unavailable: the full-screen panel with the health reason', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.state.mockRejectedValue(new ApiError(503, 'unavailable', 'the game is not available right now'));
    client.health.mockResolvedValue(healthOff);
    renderApp(client);
    const panel = await screen.findByRole('alert', { name: 'The game is off' });
    await waitFor(() => expect(panel).toHaveTextContent('JEV_API_KEY is missing'));
  });

  test('the dialogue model being offline is said in the chat column', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.health.mockResolvedValue({ ...healthOn, personas: 'down' });
    renderApp(client);
    expect(await screen.findByText(/dialogue model is offline/)).toBeInTheDocument();
  });

  test('unknown_game: back to the title with the ended banner', async () => {
    window.location.hash = '#/game/gone';
    const client = fakeApi();
    client.state.mockRejectedValue(apiError('unknown_game', 404));
    renderApp(client);
    expect(await screen.findByText(/This game has ended/)).toBeInTheDocument();
    expect(window.location.hash).toBe('#/');
  });

  test('turn_in_progress: a soft notice, the input stays disabled until the turn ends', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError('turn_in_progress'));
    let polls = 0;
    client.turns.mockImplementation(async () => {
      polls += 1;
      if (polls === 1) return [];
      if (polls < 4) return [{ ...transcript[0]!, complete: false, events: [] }];
      return [transcript[0]!];
    });
    renderApp(client);
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await userEvent.type(box, 'hello{Enter}');
    expect(await screen.findByText(/already running/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled());
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled());
  });

  test.each([
    ['too_many_games', 429, '1000 games are open'],
    ['bad_save', 500, 'the save could not be written'],
    ['bad_argument', 422, 'no such preset'],
    ['bad_request', 422, 'text: too long'],
    ['internal', 500, 'something went wrong'],
  ])('%s: a toast with the server message', async (code, status, message) => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.save.mockRejectedValue(new ApiError(status, code, message));
    renderApp(client);
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  test('connection lost mid-turn: a notice, then state and transcript reload', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.turn.mockResolvedValueOnce(droppedAfter(transcript[1]!.events.slice(0, 2)));
    client.turns.mockResolvedValueOnce([]).mockResolvedValue([transcript[1]!]);
    client.state.mockResolvedValueOnce(states[0]!).mockResolvedValue(states[2]!);
    renderApp(client);
    await userEvent.type(await screen.findByRole('textbox', { name: 'Message' }), 'search the long gallery{Enter}');
    expect(await screen.findByText(/Connection lost/)).toBeInTheDocument();
    expect(await screen.findByText('You find a stained glass by the body.')).toBeInTheDocument();
  });

  test('Save copies the board under the save name', async () => {
    window.location.hash = '#/game/g1';
    storeBoard(gameKey('g1'), { positions: { 'suspect:Mr Grey the butler': { x: 3, y: 4 } }, threads: [] });
    renderApp();
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved as 0123456789abcdef.')).toBeInTheDocument();
    expect(loadBoard(saveKey('0123456789abcdef')).positions['suspect:Mr Grey the butler']).toEqual({ x: 3, y: 4 });
  });

  test.each([
    ['won', 'CASE CLOSED'],
    ['lost', 'FILE REMAINS OPEN'],
    ['gave_up', 'FILE REMAINS OPEN'],
  ] as const)('a reloaded game that ended %s shows the ceremony (%s)', async (outcome, stamp) => {
    window.location.hash = '#/game/g1';
    renderApp(fakeApi({ state: { ...states[10]!, outcome }, turns: transcript }));
    expect(await screen.findByRole('dialog', { name: 'Case result' })).toHaveTextContent(stamp);
    await userEvent.click(screen.getByRole('button', { name: 'Back to the board' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Show the answer' }));
    expect(screen.getByRole('dialog', { name: 'Case result' })).toBeInTheDocument();
  });

  test('New case from the reveal goes back to the title', async () => {
    window.location.hash = '#/game/g1';
    renderApp(fakeApi({ state: states[10], turns: transcript }));
    await userEvent.click(await screen.findByRole('button', { name: 'New case' }));
    expect(window.location.hash).toBe('#/');
  });
});

describe('App hardening', () => {
  test('a game that ended without a reveal shows a plain notice, not a crash', async () => {
    window.location.hash = '#/game/g1';
    renderApp(fakeApi({ state: { ...states[10]!, outcome: 'won', reveal: null }, turns: transcript }));
    expect(await screen.findByText(/This case is closed/)).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('while the ceremony is open the rest of the app is inert; closing restores it', async () => {
    window.location.hash = '#/game/g1';
    renderApp(fakeApi({ state: states[10], turns: transcript }));
    const dialog = await screen.findByRole('dialog', { name: 'Case result' });
    expect(document.querySelector('[inert]')).not.toBeNull();
    expect(document.querySelector('[inert]')).not.toContainElement(dialog);
    await userEvent.click(screen.getByRole('button', { name: 'Back to the board' }));
    expect(document.querySelector('[inert]')).toBeNull();
  });

  test('Save without a stored board does not write a layout under the save name', async () => {
    window.location.hash = '#/game/g1';
    window.localStorage.clear();
    renderApp();
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved as 0123456789abcdef.')).toBeInTheDocument();
    expect(window.localStorage.getItem(saveKey('0123456789abcdef'))).toBeNull();
  });

  test('a failed Save never copies the layout', async () => {
    window.location.hash = '#/game/g1';
    storeBoard(gameKey('g1'), { positions: { a: { x: 1, y: 1 } }, threads: [] });
    const client = fakeApi();
    client.save.mockRejectedValue(new ApiError(500, 'bad_save', 'the save could not be written'));
    renderApp(client);
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }));
    await screen.findByText('the save could not be written');
    expect(window.localStorage.getItem(saveKey('0123456789abcdef'))).toBeNull();
  });

  test('a save error that lands after leaving the desk shows no toast', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    let fail: (e: unknown) => void = () => undefined;
    client.save.mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
    renderApp(client);
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }));
    await userEvent.click(screen.getByRole('button', { name: 'Case files' }));
    await screen.findByRole('heading', { name: 'GUMSHOE' });
    await act(async () => fail(new ApiError(500, 'bad_save', 'the save could not be written')));
    expect(screen.queryByText('the save could not be written')).not.toBeInTheDocument();
  });

  test('the production query client does not refetch on window focus', () => {
    expect(defaultQueryClient().getDefaultOptions().queries?.refetchOnWindowFocus).toBe(false);
  });
});

describe('App follow-up fixes', () => {
  test.each([
    ['a 500', () => apiError('internal', 500, 'something went wrong')],
    ['a network error', () => new ApiError(0, 'network', 'offline')],
    ['a non-API error', () => new TypeError('boom')],
  ])('a first load that fails with %s offers Retry and Case files, and Retry opens the desk', async (_n, make) => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.state.mockRejectedValueOnce(make());
    renderApp(client);
    expect(await screen.findByText(/Couldn't open the case file/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Case files' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('navigation', { name: 'Notebook' })).toBeInTheDocument();
  });

  test('Case files on the load-failure panel goes to the title', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.state.mockRejectedValue(new ApiError(0, 'network', 'offline'));
    renderApp(client);
    await userEvent.click(await screen.findByRole('button', { name: 'Case files' }));
    expect(window.location.hash).toBe('#/');
  });

  test('the no-reveal notice lives in the header, so the grid keeps its four rows', async () => {
    window.location.hash = '#/game/g1';
    const { container } = render(<App client={fakeApi({ state: { ...states[10]!, outcome: 'won', reveal: null }, turns: transcript })} queryClient={testQueryClient()} session={{ pollMs: 5 }} />);
    const notice = await screen.findByText(/This case is closed/);
    expect(notice.closest('header')).not.toBeNull();
    expect(container.querySelector('[data-testid="desk-main"]')!.children).toHaveLength(4);
  });

  function liveEnd() {
    window.location.hash = '#/game/g1';
    const client = fakeApi({ state: states[0], turns: [] });
    client.turn.mockResolvedValueOnce(eventsOf([{ kind: 'game_over', outcome: 'won', reveal }, { kind: 'done', turn_ms: 1 }]));
    let resolve: (s: typeof states[number]) => void = () => undefined;
    client.state.mockResolvedValueOnce(states[0]!).mockImplementationOnce(() => new Promise((r) => { resolve = r as typeof resolve; }));
    client.state.mockResolvedValue(states[10]!);
    return { client, finish: () => act(async () => resolve(states[10]!)) };
  }

  test('a live game over opens the ceremony; once closed, the state refresh does not reopen it', async () => {
    const { client, finish } = liveEnd();
    renderApp(client);
    await userEvent.type(await screen.findByRole('textbox', { name: 'Message' }), 'I accuse the butler{Enter}');
    await screen.findByRole('dialog', { name: 'Case result' });
    await userEvent.click(screen.getByRole('button', { name: 'Back to the board' }));
    await waitFor(() => expect(client.state).toHaveBeenCalledTimes(2));
    await finish();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('closing the ceremony moves focus to the Show the answer button', async () => {
    const { client, finish } = liveEnd();
    renderApp(client);
    await userEvent.type(await screen.findByRole('textbox', { name: 'Message' }), 'I accuse the butler{Enter}');
    await screen.findByRole('dialog', { name: 'Case result' });
    await userEvent.click(screen.getByRole('button', { name: 'Back to the board' }));
    await finish();
    expect(screen.getByRole('button', { name: 'Show the answer' })).toHaveFocus();
  });

  test('Accuse keeps text the player already typed', async () => {
    window.location.hash = '#/game/g1';
    renderApp();
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await userEvent.type(box, 'was it the butler');
    await userEvent.click(screen.getByRole('button', { name: 'Accuse' }));
    expect(box).toHaveValue('was it the butler');
    expect(box).toHaveFocus();
  });

  test('two synchronous clicks on Save start one save', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.save.mockImplementation(() => new Promise(() => undefined));
    renderApp(client);
    const button = await screen.findByRole('button', { name: 'Save' });
    act(() => {
      button.click();
      button.click();
    });
    await waitFor(() => expect(client.save).toHaveBeenCalled());
    expect(client.save).toHaveBeenCalledTimes(1);
  });

  test('a sent message leaves the box empty once the turn completes', async () => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    // the post-turn state fetch takes a real tick, as it does over the network, so the player message renders mid-send
    const first = client.state.getMockImplementation()!;
    client.state.mockImplementation(async (id) => {
      await new Promise((r) => setTimeout(r, 20));
      return first(id);
    });
    renderApp(client);
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await userEvent.type(box, 'search the gallery{Enter}');
    await waitFor(() => expect(client.turn).toHaveBeenCalled());
    await waitFor(() => expect(client.state.mock.calls.length).toBeGreaterThan(1));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50)); // let the send settle: a wrongly restored draft lands after it
    });
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('');
  });

  test.each([
    ['turn_in_progress', 409],
    ['bad_request', 400],
  ])('a send refused with %s before a turn starts puts the text back', async (code, status) => {
    window.location.hash = '#/game/g1';
    const client = fakeApi();
    client.turn.mockRejectedValueOnce(apiError(code, status));
    renderApp(client);
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await userEvent.type(box, 'search the gallery{Enter}');
    await waitFor(() => expect(client.turn).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('search the gallery'));
  });
});
