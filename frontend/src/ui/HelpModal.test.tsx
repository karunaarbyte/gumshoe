import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { HelpModal } from './HelpModal';

test('the how-to-play card explains the real rules and closes on Escape or Got it', async () => {
  const onClose = vi.fn();
  render(<HelpModal onClose={onClose} />);
  const dialog = screen.getByRole('dialog', { name: 'How to play' });
  expect(dialog).toHaveTextContent('Search places');
  expect(dialog).toHaveTextContent('read the records about');
  expect(dialog).toHaveTextContent('hold a lead on');
  expect(dialog).toHaveTextContent('Yes button');
  expect(dialog).toHaveTextContent('Type help');
  await userEvent.keyboard('{Escape}');
  expect(onClose).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: 'Got it' }));
  expect(onClose).toHaveBeenCalledTimes(2);
});
