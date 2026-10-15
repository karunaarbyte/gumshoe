import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { ToastProvider, useToast } from './toast';

function Trigger({ message, tone }: { message: string; tone?: 'error' | 'notice' }) {
  const toast = useToast();
  return (
    <button type="button" onClick={() => toast.show(message, tone)}>
      go
    </button>
  );
}

test('an error toast is an alert; a notice is a status', async () => {
  render(
    <ToastProvider>
      <Trigger message="1000 games are open" />
      <Trigger message="Saved as abc." tone="notice" />
    </ToastProvider>,
  );
  const [error, notice] = screen.getAllByRole('button', { name: 'go' });
  await userEvent.click(error!);
  await userEvent.click(notice!);
  expect(screen.getByRole('alert')).toHaveTextContent('1000 games are open');
  expect(screen.getByRole('status')).toHaveTextContent('Saved as abc.');
});

test('a toast can be dismissed and goes by itself', async () => {
  render(
    <ToastProvider durationMs={30}>
      <Trigger message="gone soon" />
    </ToastProvider>,
  );
  await userEvent.click(screen.getByRole('button', { name: 'go' }));
  await userEvent.click(screen.getByRole('button', { name: 'dismiss' }));
  expect(screen.queryByText('gone soon')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'go' }));
  await waitFor(() => expect(screen.queryByText('gone soon')).not.toBeInTheDocument());
});

test('useToast outside the provider is a programming error', () => {
  expect(() => render(<Trigger message="x" />)).toThrow('useToast needs a ToastProvider');
});
