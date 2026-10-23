import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { gameKey, loadBoard, saveKey, storeBoard } from '../board/storage';
import { healthOff } from '../test/fixtures';
import { fakeApi } from '../test/fakeApi';
import { renderWithApp } from '../test/render';
import { TitleScreen, parseSeed } from './TitleScreen';

function setup(client = fakeApi(), banner: string | null = null) {
  const onOpen = vi.fn();
  const onError = vi.fn();
  renderWithApp(<TitleScreen onOpen={onOpen} onError={onError} banner={banner} />, client);
  return { client, onOpen, onError };
}

describe('parseSeed', () => {
  test('empty is random, digits are a seed, anything else is refused', () => {
    expect(parseSeed('', () => 0.5)).toBe(2 ** 30);
    expect(parseSeed(' 42 ')).toBe(42);
    expect(parseSeed('-1')).toBeNull();
    expect(parseSeed('1.5')).toBeNull();
    expect(parseSeed('99999999999999999999')).toBeNull();
  });
});

describe('TitleScreen', () => {
  test('there is no Stats button and the privacy line is shown', async () => {
    setup();
    expect(screen.queryByRole('button', { name: 'Stats' })).not.toBeInTheDocument();
    expect(screen.getByText('Your messages are kept to compare AI models.')).toBeInTheDocument();
  });

  test('starts a new case with the seed and the chosen preset', async () => {
    const { client, onOpen } = setup();
    await userEvent.type(screen.getByRole('textbox', { name: 'Seed (optional)' }), '7');
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Preset' }), 'short');
    await userEvent.click(screen.getByRole('button', { name: 'New case' }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith('g1'));
    expect(client.createGame).toHaveBeenCalledWith(7, 'short');
  });

  test('a bad seed is refused before any request', async () => {
    const { client } = setup();
    await userEvent.type(screen.getByRole('textbox', { name: 'Seed (optional)' }), 'abc');
    await waitFor(() => expect(screen.getByRole('button', { name: 'New case' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'New case' }));
    expect(screen.getByText(/whole number/)).toBeInTheDocument();
    expect(client.createGame).not.toHaveBeenCalled();
  });

  test('lists saves and loads one, bringing its board along', async () => {
    const client = fakeApi();
    client.saves.mockResolvedValue([{ name: '0123456789abcdef', created_at: '2026-10-15T10:00:00+00:00', pack: 'castle', status: 'playing' }]);
    storeBoard(saveKey('0123456789abcdef'), { positions: { 'suspect:X': { x: 1, y: 2 } }, threads: [] });
    const { onOpen } = setup(client);
    const saves = await screen.findByRole('region', { name: 'Saved games' });
    await userEvent.click(await within(saves).findByRole('button', { name: 'Load' }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith('g2'));
    expect(client.loadGame).toHaveBeenCalledWith('0123456789abcdef');
    expect(loadBoard(gameKey('g2')).positions['suspect:X']).toEqual({ x: 1, y: 2 });
  });

  test('lists open games with outcome and turn_running; Resume and Close', async () => {
    const client = fakeApi();
    client.games.mockResolvedValue([{ game: 'g9', preset: 'standard', outcome: 'lost', attempts_left: 0, turn_running: true }]);
    const { onOpen } = setup(client);
    const open = await screen.findByRole('region', { name: 'Open games' });
    expect(await within(open).findByText('turn running')).toBeInTheDocument();
    expect(within(open).getByText('lost')).toBeInTheDocument();
    await userEvent.click(within(open).getByRole('button', { name: 'Resume' }));
    expect(onOpen).toHaveBeenCalledWith('g9');
    await userEvent.click(within(open).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(client.deleteGame).toHaveBeenCalledWith('g9'));
  });

  test('when the game is off: banner with the reason, controls disabled', async () => {
    const client = fakeApi();
    client.health.mockResolvedValue(healthOff);
    client.games.mockResolvedValue([{ game: 'g9', preset: 'standard', outcome: 'playing', attempts_left: 3, turn_running: false }]);
    setup(client);
    expect(await screen.findByText(/JEV_API_KEY is missing/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New case' })).toBeDisabled();
    expect(await screen.findByRole('button', { name: 'Resume' })).toBeDisabled();
  });

  test('a refused create goes to onError', async () => {
    const client = fakeApi();
    client.createGame.mockRejectedValue(new ApiError(429, 'too_many_games', '1000 games are open'));
    const { onError } = setup(client);
    await waitFor(() => expect(screen.getByRole('button', { name: 'New case' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'New case' }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'too_many_games' })));
  });

  test('shows the banner it is given', () => {
    setup(fakeApi(), 'This game has ended (the server may have restarted).');
    expect(screen.getByRole('alert')).toHaveTextContent('server may have restarted');
  });
});
