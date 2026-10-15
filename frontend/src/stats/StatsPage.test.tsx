import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';
import { apiError, fakeApi } from '../test/fakeApi';
import { renderWithApp } from '../test/render';
import { StatsPage } from './StatsPage';

function show(client = fakeApi()) {
  const onBack = vi.fn();
  renderWithApp(<StatsPage onBack={onBack} />, client);
  return { client, onBack };
}

describe('StatsPage', () => {
  test('leads with what agreement means, before any number', async () => {
    show();
    const box = await screen.findByRole('region', {
      name: 'What agreement means',
    });
    expect(box).toHaveTextContent('not that either is right');
    expect(box).toHaveTextContent('answered in time');
  });

  test('each node says how much of it the comparison covers', async () => {
    show();
    expect(await screen.findByTestId('compared-understand')).toHaveTextContent('165 of 228 decisions compared · 63 nimble errors · 0 fallbacks');
    expect(screen.getByTestId('compared-post_check')).toHaveTextContent('68 of 68 decisions compared');
  });

  test('agreement is shown per question with its sample and its range', async () => {
    show();
    const node = await screen.findByRole('region', { name: 'Node understand' });
    expect(within(node).getByText('118/165 (72%) · 95% range 64%–78%')).toBeInTheDocument();
    expect(within(node).getByText(/average difference: \+0.38 \(shadow scores higher\)/)).toBeInTheDocument();
  });

  test('the two backends sit side by side with their roles and their timeout rate', async () => {
    show();
    const node = await screen.findByRole('region', { name: 'Node understand' });
    const table = within(node).getByRole('table', { name: /side by side/ });
    expect(within(table).getByRole('columnheader', { name: /jev .*decides/ })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: /nimble .*shadow/ })).toBeInTheDocument();
    expect(within(table).getByText('63 (28%)')).toBeInTheDocument();
    expect(within(table).getAllByText('answered calls only').length).toBeGreaterThan(0);
  });

  test('tokens and confidence are kept apart as not comparable', async () => {
    show();
    const node = await screen.findByRole('region', { name: 'Node understand' });
    expect(within(node).getByText(/not comparable between models/)).toBeInTheDocument();
  });

  test('the notes count the shadow errors from the data, not from a fixed sentence', async () => {
    show();
    const notes = await screen.findByRole('region', { name: 'Notes' });
    expect(notes).toHaveTextContent('69 errors');
    expect(notes).toHaveTextContent('runs on the same model server');
  });

  test('cost says the price is not set rather than pretending it is free', async () => {
    show();
    const node = await screen.findByRole('region', { name: 'Node understand' });
    expect(within(node).getByText('price not set (JEV_USD_PER_MTOK_IN/OUT)')).toBeInTheDocument();
    expect(within(node).getByText('price not set (NIMBLE_USD_PER_MTOK_IN/OUT)')).toBeInTheDocument();
  });

  test('including cold calls asks the server again', async () => {
    const { client } = show();
    await screen.findByRole('region', { name: 'Node understand' });
    await userEvent.click(screen.getByLabelText(/Include cold calls/));
    await waitFor(() =>
      expect(client.stats).toHaveBeenLastCalledWith({
        since: undefined,
        includeCold: true,
      }),
    );
  });

  test('a since date is sent as local midnight in UTC, and also filters the disagreements', async () => {
    const { client } = show();
    await screen.findByRole('region', { name: 'Node understand' });
    await userEvent.type(screen.getByLabelText('Since'), '2026-10-15');
    const iso = new Date(2026, 9, 15).toISOString();
    await waitFor(() =>
      expect(client.stats).toHaveBeenLastCalledWith({
        since: iso,
        includeCold: false,
      }),
    );
    await waitFor(() =>
      expect(client.disagreements).toHaveBeenLastCalledWith({
        node: undefined,
        question: undefined,
        since: iso,
      }),
    );
  });

  test('the disagreements open into the side-by-side table, and use the servers verdict on agreement', async () => {
    show();
    const row = await screen.findByRole('button', { name: /differ on weight/ });
    expect(row).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');
    const table = await screen.findByTestId('decision-dec-weight');
    const rows = within(table).getAllByRole('row');
    expect(rows.find((r) => r.textContent?.startsWith('weight'))).toHaveAttribute('data-disagree', 'true');
    expect(rows.find((r) => r.textContent?.startsWith('intent'))).toHaveAttribute('data-disagree', 'false');
  });

  test('narrowing the disagreements to a question asks the server for just that', async () => {
    const { client } = show();
    await screen.findByRole('region', { name: 'Disagreements' });
    await userEvent.selectOptions(screen.getByLabelText('Node'), 'understand');
    await userEvent.selectOptions(screen.getByLabelText('Question'), 'weight');
    await waitFor(() =>
      expect(client.disagreements).toHaveBeenLastCalledWith({
        node: 'understand',
        question: 'weight',
        since: undefined,
      }),
    );
  });

  test('a question filter that the chosen node does not have is dropped, not sent', async () => {
    const { client } = show();
    await screen.findByRole('region', { name: 'Disagreements' });
    await userEvent.selectOptions(screen.getByLabelText('Node'), 'understand');
    await userEvent.selectOptions(screen.getByLabelText('Question'), 'weight');
    await userEvent.selectOptions(screen.getByLabelText('Node'), 'post_check');
    expect(screen.getByLabelText('Question')).toHaveValue('');
    await waitFor(() => expect(client.disagreements).toHaveBeenLastCalledWith({ node: 'post_check', question: undefined, since: undefined }));
  });

  test('with nothing recorded it says how to collect data', async () => {
    const client = fakeApi();
    client.stats.mockResolvedValue({
      generated_at: 'x',
      since: null,
      include_cold: false,
      nodes: [],
    });
    show(client);
    expect(await screen.findByText(/No decisions recorded yet/)).toHaveTextContent('SHADOW_RUN=true');
  });

  test('a failing stats call shows its message and the page stays usable', async () => {
    const client = fakeApi();
    client.stats.mockRejectedValue(apiError('internal', 500, 'the stats database is locked'));
    const { onBack } = show(client);
    expect(await screen.findByRole('alert')).toHaveTextContent('the stats database is locked');
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalled();
  });

  test('a node nobody shadowed says there is nothing to compare', async () => {
    const client = fakeApi();
    const base = (await client.stats()).nodes.find((n) => n.node === 'understand')!;
    client.stats.mockResolvedValue({
      generated_at: 'x',
      since: null,
      include_cold: false,
      nodes: [
        {
          ...base,
          compared: 0,
          shadow_errors: 0,
          question_agreement: {},
          backends: base.backends.filter((b) => b.role === 'primary'),
        },
      ],
    });
    show(client);
    expect(await screen.findByText(/No shadow ran on this node/)).toBeInTheDocument();
  });
});
