import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { states } from '../test/fixtures';
import { Notebook } from './Notebook';

test('facts by source with speaker, records and contradictions', () => {
  render(<Notebook state={states[2]!} canAccuse onAccuse={vi.fn()} />);
  const grey = screen.getByRole('region', { name: 'Mr Grey the butler' });
  expect(grey).toHaveTextContent('Mr Grey the butler: He was in the pantry all evening.');
  expect(within(grey).getByText('contradicted')).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Records' })).toHaveTextContent('Household ledger');
  expect(screen.getByRole('region', { name: 'Contradictions' })).toHaveTextContent('Grey says pantry');
});

test('an empty notebook says so', () => {
  render(<Notebook state={states[0]!} canAccuse onAccuse={vi.fn()} />);
  expect(screen.getByText('Nothing noted yet.')).toBeInTheDocument();
});

test('the Accuse button calls back and can be disabled', async () => {
  const onAccuse = vi.fn();
  const { rerender } = render(<Notebook state={states[0]!} canAccuse onAccuse={onAccuse} />);
  await userEvent.click(screen.getByRole('button', { name: 'Accuse' }));
  expect(onAccuse).toHaveBeenCalledOnce();
  rerender(<Notebook state={states[0]!} canAccuse={false} onAccuse={onAccuse} />);
  expect(screen.getByRole('button', { name: 'Accuse' })).toBeDisabled();
});

test('the notebook collapses to a slim rail that still accuses', async () => {
  const onToggle = vi.fn();
  const onAccuse = vi.fn();
  const { rerender } = render(<Notebook state={states[2]!} canAccuse onAccuse={onAccuse} onToggle={onToggle} />);
  await userEvent.click(screen.getByRole('button', { name: 'Hide the notebook' }));
  expect(onToggle).toHaveBeenCalledOnce();
  rerender(<Notebook state={states[2]!} canAccuse onAccuse={onAccuse} onToggle={onToggle} collapsed />);
  expect(screen.queryByRole('region', { name: 'Mr Grey the butler' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Accuse' }));
  expect(onAccuse).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole('button', { name: 'Open the notebook' }));
  expect(onToggle).toHaveBeenCalledTimes(2);
});
