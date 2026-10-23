import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { clearAdminToken, getAdminToken, setAdminToken } from '../api/adminToken';
import { AdminGate } from './AdminGate';

beforeEach(() => {
  clearAdminToken();
});

afterEach(() => {
  clearAdminToken();
});

test('without a token it asks for one and shows nothing else', async () => {
  render(
    <AdminGate onBack={vi.fn()}>
      <p>secret page</p>
    </AdminGate>,
  );
  const field = screen.getByLabelText('Admin token');
  expect(field).toHaveAttribute('type', 'password');
  expect(field).toHaveAttribute('autocomplete', 'off');
  expect(screen.queryByText('secret page')).not.toBeInTheDocument();
});

test('entering a token stores it and shows the page', async () => {
  render(
    <AdminGate onBack={vi.fn()}>
      <p>secret page</p>
    </AdminGate>,
  );
  await userEvent.type(screen.getByLabelText('Admin token'), 'fake-gate-token');
  expect(document.body.innerHTML).not.toContain('fake-gate-token');
  await userEvent.click(screen.getByRole('button', { name: 'Open the stats' }));
  expect(await screen.findByText('secret page')).toBeInTheDocument();
  expect(getAdminToken()).toBe('fake-gate-token');
  expect(document.body.innerHTML).not.toContain('fake-gate-token');
});

test('a stored token opens the page straight away', () => {
  setAdminToken('fake-stored');
  render(
    <AdminGate onBack={vi.fn()}>
      <p>secret page</p>
    </AdminGate>,
  );
  expect(screen.getByText('secret page')).toBeInTheDocument();
});

test('an empty token is not accepted', async () => {
  render(
    <AdminGate onBack={vi.fn()}>
      <p>secret page</p>
    </AdminGate>,
  );
  await userEvent.type(screen.getByLabelText('Admin token'), '   ');
  await userEvent.click(screen.getByRole('button', { name: 'Open the stats' }));
  expect(screen.queryByText('secret page')).not.toBeInTheDocument();
  expect(getAdminToken()).toBeNull();
});

test('the notice is shown when given', () => {
  render(
    <AdminGate onBack={vi.fn()} notice="That token did not work, or the stats are switched off.">
      <p>x</p>
    </AdminGate>,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('That token did not work, or the stats are switched off.');
});

test('Back leaves', async () => {
  const onBack = vi.fn();
  render(
    <AdminGate onBack={onBack}>
      <p>x</p>
    </AdminGate>,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(onBack).toHaveBeenCalled();
});
