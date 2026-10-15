import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
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
});
