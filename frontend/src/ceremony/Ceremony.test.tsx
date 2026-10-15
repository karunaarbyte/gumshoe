import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { reveal } from '../test/fixtures';
import { preferReducedMotion } from '../test/render';
import { Ceremony, stampText, type Ended } from './Ceremony';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('Ceremony', () => {
  test('stamp text per outcome', () => {
    expect(stampText('won')).toBe('CASE CLOSED');
    expect(stampText('lost')).toBe('FILE REMAINS OPEN');
    expect(stampText('gave_up')).toBe('FILE REMAINS OPEN');
  });

  test('plays thread, then stamp, then the reveal', async () => {
    preferReducedMotion(false);
    render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} timing={{ thread: 20, stamp: 20 }} />);
    expect(screen.getByTestId('ceremony-stage')).toHaveTextContent('Mr Grey the butler');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(await screen.findByRole('status')).toHaveTextContent('CASE CLOSED');
    expect(await screen.findByRole('article', { name: 'The answer' })).toHaveTextContent('poisoned port');
  });

  test('with reduced motion: a static reveal at once, no stage', () => {
    preferReducedMotion(true);
    render(<Ceremony outcome="lost" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByTestId('ceremony-stage')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('FILE REMAINS OPEN');
    const card = screen.getByRole('article', { name: 'The answer' });
    for (const v of Object.values(reveal)) expect(card).toHaveTextContent(v);
  });

  test('New case and Back to the board call back', async () => {
    preferReducedMotion(true);
    const onNewCase = vi.fn();
    const onClose = vi.fn();
    render(<Ceremony outcome="gave_up" reveal={reveal} onNewCase={onNewCase} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: 'New case' }));
    await userEvent.click(screen.getByRole('button', { name: 'Back to the board' }));
    expect(onNewCase).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  test('unknown outcome reads as an open file', () => {
    expect(stampText('mystery' as Ended)).toBe('FILE REMAINS OPEN');
  });

  test('focus moves into the dialog and is restored afterwards', () => {
    preferReducedMotion(true);
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: 'Case result' }).contains(document.activeElement)).toBe(true);
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  test('Escape during the animation jumps to the reveal; on the reveal it closes', async () => {
    preferReducedMotion(false);
    const onClose = vi.fn();
    render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={onClose} timing={{ thread: 5000, stamp: 5000 }} />);
    expect(screen.queryByRole('article', { name: 'The answer' })).not.toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.getByRole('article', { name: 'The answer' })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
  });

  test('Tab stays inside the dialog', async () => {
    preferReducedMotion(true);
    render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog', { name: 'Case result' });
    for (let i = 0; i < 5; i++) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await userEvent.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  test('a persistent live region announces the stamp text', async () => {
    preferReducedMotion(false);
    const { container } = render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} timing={{ thread: 20, stamp: 20 }} />);
    const live = container.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(live).toBeEmptyDOMElement();
    await screen.findByRole('status');
    expect(container.querySelector('[aria-live="polite"]')).toBe(live);
    expect(live).toHaveTextContent('CASE CLOSED');
  });

  test('timers are cleared on unmount', () => {
    preferReducedMotion(false);
    vi.useFakeTimers();
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { unmount } = render(<Ceremony outcome="won" reveal={reveal} onNewCase={vi.fn()} onClose={vi.fn()} timing={{ thread: 100, stamp: 100 }} />);
    unmount();
    vi.advanceTimersByTime(1000);
    expect(vi.getTimerCount()).toBe(0);
    expect(err).not.toHaveBeenCalled();
  });
});
