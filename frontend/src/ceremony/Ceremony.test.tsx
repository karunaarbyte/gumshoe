import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { reveal } from '../test/fixtures';
import { preferReducedMotion } from '../test/render';
import { Ceremony, stampText } from './Ceremony';

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
});
