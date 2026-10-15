import userEvent from '@testing-library/user-event';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { states } from '../test/fixtures';
import { preferReducedMotion } from '../test/render';
import { Board } from './Board';
import { buildCards, factCard, suspectCard } from './cards';
import { initialLayout } from './layout';
import { gameKey, loadBoard } from './storage';

const state = states[2]!;
const S1 = suspectCard('Mr Grey the butler');
const S2 = suspectCard('Mrs Pike the cook');
const F2 = factCard('Mr Grey the butler', 'He was in the pantry all evening.');

describe('Board', () => {
  test('shows every card; a locked one is redacted', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    expect(screen.getByRole('article', { name: 'Suspect: Mr Grey the butler' })).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Suspect, locked' })).toHaveTextContent('REDACTED');
    expect(screen.queryByText('Dr Wren the physician')).not.toBeInTheDocument();
  });

  test('a locked card never leaks its name or id into the DOM', () => {
    preferReducedMotion(true);
    const { container } = render(<Board game="g1" state={state} />);
    expect(container.innerHTML).not.toContain('Dr Wren');
    expect(screen.getByRole('button', { name: 'Pin on suspect, locked' })).toBeInTheDocument();
  });

  test('a card that unlocks shows its face, flipping over', () => {
    preferReducedMotion(false);
    const { rerender } = render(<Board game="g1" state={state} />);
    const unlocked = { ...state, brief: { ...state.brief, suspects: state.brief.suspects.map((s) => ({ ...s, locked: false })) } };
    rerender(<Board game="g1" state={unlocked} />);
    expect(screen.getByRole('article', { name: 'Suspect: Dr Wren the physician' })).toBeInTheDocument();
    expect(screen.getByTestId(`card-${suspectCard('Dr Wren the physician')}`)).toHaveAttribute('data-flipped', 'true');
    expect(screen.getByTestId(`card-${S1}`)).toHaveAttribute('data-flipped', 'false');
  });

  test('a contradicted fact carries the stamp', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    expect(screen.getByTestId(`card-${F2}`)).toHaveTextContent('CONTRADICTED');
  });

  test('draws one red string per game string', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    expect(screen.getAllByTestId('game-string')).toHaveLength(4);
  });

  test('dragging a card moves it and stores the position under the game id', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    const start = initialLayout(buildCards(state))[S1]!;
    const card = screen.getByTestId(`card-${S1}`);
    fireEvent.pointerDown(card, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(screen.getByTestId('board'), { clientX: 150, clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(screen.getByTestId('board'), { clientX: 150, clientY: 130, pointerId: 1 });
    expect(card.style.left).toBe(`${start.x + 50}px`);
    expect(loadBoard(gameKey('g1')).positions[S1]).toEqual({ x: start.x + 50, y: start.y + 30 });
  });

  test('pin to card makes a thread; clicking the thread deletes it', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Pin on suspect Mr Grey the butler' }), { pointerId: 1 });
    fireEvent.pointerUp(screen.getByTestId(`card-${S2}`), { pointerId: 1 });
    expect(screen.getAllByTestId('player-thread')).toHaveLength(1);
    expect(loadBoard(gameKey('g1')).threads).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Delete thread' }));
    expect(screen.queryAllByTestId('player-thread')).toHaveLength(0);
    expect(loadBoard(gameKey('g1')).threads).toEqual([]);
  });

  test('a thread dropped on its own card or on the cork is not made', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Pin on suspect Mr Grey the butler' }), { pointerId: 1 });
    fireEvent.pointerUp(screen.getByTestId(`card-${S1}`), { pointerId: 1 });
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Pin on suspect Mr Grey the butler' }), { pointerId: 1 });
    fireEvent.pointerUp(screen.getByTestId('board'), { pointerId: 1 });
    expect(screen.queryAllByTestId('player-thread')).toHaveLength(0);
  });

  test('a stored arrangement is restored', () => {
    preferReducedMotion(true);
    window.localStorage.setItem(gameKey('g1'), JSON.stringify({ positions: { [S1]: { x: 7, y: 8 } }, threads: [{ id: 't', from: S1, to: S2 }] }));
    render(<Board game="g1" state={state} />);
    expect(screen.getByTestId(`card-${S1}`).style.left).toBe('7px');
    expect(screen.getAllByTestId('player-thread')).toHaveLength(1);
  });

  test('a drag writes storage once, on release', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    const start = initialLayout(buildCards(state))[S1]!;
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    const board = screen.getByTestId('board');
    fireEvent.pointerDown(screen.getByTestId(`card-${S1}`), { clientX: 100, clientY: 100, pointerId: 1 });
    for (const dx of [10, 20, 30, 40]) fireEvent.pointerMove(board, { clientX: 100 + dx, clientY: 100, pointerId: 1 });
    expect(spy).not.toHaveBeenCalledWith(gameKey('g1'), expect.anything());
    fireEvent.pointerUp(board, { clientX: 140, clientY: 100, pointerId: 1 });
    expect(spy.mock.calls.filter(([k]) => k === gameKey('g1'))).toHaveLength(1);
    expect(loadBoard(gameKey('g1')).positions[S1]).toEqual({ x: start.x + 40, y: start.y });
    spy.mockRestore();
  });

  test('loading a game does not rewrite its storage', () => {
    preferReducedMotion(true);
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    render(<Board game="g1" state={state} />);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  test('a lost mouse-up ends the drag', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    const card = screen.getByTestId(`card-${S1}`);
    const board = screen.getByTestId('board');
    fireEvent.pointerDown(card, { clientX: 100, clientY: 100, pointerId: 1, pointerType: 'mouse', buttons: 1 });
    fireEvent.pointerMove(board, { clientX: 120, clientY: 100, pointerId: 1, pointerType: 'mouse', buttons: 1 });
    const before = card.style.left;
    fireEvent.pointerMove(board, { clientX: 200, clientY: 100, pointerId: 1, pointerType: 'mouse', buttons: 0 });
    fireEvent.pointerMove(board, { clientX: 300, clientY: 100, pointerId: 1, pointerType: 'mouse', buttons: 1 });
    expect(card.style.left).not.toBe(before); // the cancelled drag snaps back
    const after = card.style.left;
    fireEvent.pointerMove(board, { clientX: 400, clientY: 100, pointerId: 1, pointerType: 'mouse', buttons: 1 });
    expect(card.style.left).toBe(after);
  });

  test('a right-button press starts no drag', () => {
    preferReducedMotion(true);
    render(<Board game="g1" state={state} />);
    const card = screen.getByTestId(`card-${S1}`);
    const before = card.style.left;
    fireEvent.pointerDown(card, { clientX: 100, clientY: 100, pointerId: 1, button: 2 });
    fireEvent.pointerMove(screen.getByTestId('board'), { clientX: 160, clientY: 100, pointerId: 1 });
    expect(card.style.left).toBe(before);
  });

  test('a thread can be deleted from the keyboard', async () => {
    preferReducedMotion(true);
    window.localStorage.setItem(gameKey('g1'), JSON.stringify({ positions: {}, threads: [{ id: 't', from: S1, to: S2 }] }));
    render(<Board game="g1" state={state} />);
    screen.getByRole('button', { name: 'Delete thread' }).focus();
    await userEvent.keyboard('{Enter}');
    expect(screen.queryAllByTestId('player-thread')).toHaveLength(0);
  });
});
