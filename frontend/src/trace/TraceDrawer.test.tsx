import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError } from '../api/errors';
import { rebuild } from '../game/rebuild';
import { decision, decisionIds, healthOn, states, transcript } from '../test/fixtures';
import { fakeApi } from '../test/fakeApi';
import { renderWithApp } from '../test/render';
import { totals } from './compare';
import { DecisionTable } from './DecisionPanel';
import { TraceDrawer } from './TraceDrawer';

const turns = rebuild('g1', states[3]!, transcript.slice(0, 3)).turns;

async function openTurn(text: string) {
  await userEvent.click(screen.getByRole('button', { name: 'Open the trace' }));
  await userEvent.click(screen.getByRole('button', { name: new RegExp(text) }));
}

describe('DecisionTable', () => {
  test('highlights what the server says disagrees, not what merely reads differently', () => {
    // weight differs as text (2.40 vs 2.60) but both sit in one band: the server says it agrees
    const d = decision('x', ['search', 'search']);
    d.calls[0]!.answers.weight = { verdict: '2.40', confidence: 0.6 };
    d.calls[1]!.answers.weight = { verdict: '2.60', confidence: 0.3 };
    d.agrees = { intent: true, weight: true };
    render(<DecisionTable decision={d} backends={[]} />);
    const rows = screen.getAllByRole('row');
    expect(rows.find((r) => r.textContent?.startsWith('weight'))).toHaveAttribute('data-disagree', 'false');
  });

  test('a decision that is not a head-to-head highlights nothing', () => {
    const d = decision('y', ['search', 'meta']);
    d.agrees = {};
    render(<DecisionTable decision={d} backends={[]} />);
    expect(screen.getAllByRole('row').every((r) => r.getAttribute('data-disagree') !== 'true')).toBe(true);
  });
});

describe('compare', () => {
  test('totals per backend', () => {
    expect(totals([decision('a'), decision('b')])).toEqual([
      { backend: 'jev', calls: 2, costUsd: 0.0008, meanLatencyMs: 120 },
      { backend: 'nimble', calls: 2, costUsd: 0.0002, meanLatencyMs: 480 },
    ]);
  });

  test('unknown cost stays null; known costs are summed around the unknown ones', () => {
    const a = decision('a');
    const b = decision('b');
    a.calls[0] = { ...a.calls[0]!, est_cost_usd: null };
    a.calls[1] = { ...a.calls[1]!, est_cost_usd: null };
    b.calls[1] = { ...b.calls[1]!, est_cost_usd: 0.0003 };
    const [jev, nimble] = totals([a, b]);
    expect(jev?.costUsd).toBe(0.0004);
    expect(nimble?.costUsd).toBe(0.0003);
    const [none] = totals([a]);
    expect(none?.costUsd).toBeNull();
  });
});

describe('TraceDrawer', () => {
  test('lists turns newest first', async () => {
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} />);
    await userEvent.click(screen.getByRole('button', { name: 'Open the trace' }));
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('#3');
    expect(items[2]).toHaveTextContent('#1');
    expect(items[0]).toHaveTextContent('interrogate → s1 (0.93)');
    expect(items[0]).toHaveTextContent('check failed');
  });

  test('a turn shows its decisions side by side and highlights disagreement', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => decision(id, ['search', 'interrogate']));
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} />, client);
    await openTurn('search the long gallery');
    const panel = await screen.findByTestId(`decision-${decisionIds.search}`);
    const rows = within(panel).getAllByRole('row');
    const intentRow = rows.find((r) => r.textContent?.startsWith('intent'));
    expect(intentRow).toHaveAttribute('data-disagree', 'true');
    expect(intentRow).toHaveTextContent('search (0.93)');
    expect(intentRow).toHaveTextContent('interrogate (0.71)');
    expect(rows.find((r) => r.textContent?.startsWith('confirms_pending'))).toHaveAttribute('data-disagree', 'false');
    expect(within(panel).getByText('used')).toBeInTheDocument();
    expect(within(panel).getByText('cold')).toBeInTheDocument();
    expect(screen.getByTestId('totals-jev')).toHaveTextContent('1 calls');
  });

  test('not_recorded_yet is retried until the decision lands', async () => {
    const client = fakeApi();
    let calls = 0;
    client.gameDecision.mockImplementation(async (_game, id) => {
      calls += 1;
      if (calls < 3) throw new ApiError(404, 'not_recorded_yet', 'not yet');
      return decision(id);
    });
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} retryBaseMs={1} />, client);
    await openTurn('search the long gallery');
    await screen.findByTestId(`decision-${decisionIds.search}`);
    expect(calls).toBe(3);
  });

  test('gives up after a few retries and says so', async () => {
    const client = fakeApi(); // every decision: not_recorded_yet
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} retryBaseMs={1} />, client);
    await openTurn('search the long gallery');
    await waitFor(() => expect(screen.getByText(/not recorded yet/)).toBeInTheDocument());
    expect(client.gameDecision).toHaveBeenCalledTimes(5);
  });

  test('an error line shows class, backend and status only, as the server gives it', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => {
      const d = decision(id);
      d.calls[1] = {
        ...d.calls[1]!,
        error: 'TimeoutError nimble 504',
        answers: {},
      };
      return d;
    });
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} />, client);
    await openTurn('search the long gallery');
    expect(await screen.findByText('error: TimeoutError nimble 504')).toBeInTheDocument();
  });

  test('with no shadow the drawer is one column', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => decision(id));
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={{ ...healthOn, shadow: null }} />, client);
    await openTurn('search the long gallery');
    const panel = await screen.findByTestId(`decision-${decisionIds.search}`);
    expect(
      within(panel)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['question', 'jev']);
  });

  test('before health has loaded, the columns come from the decision itself', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => decision(id));
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={undefined} />, client);
    await openTurn('search the long gallery');
    const panel = await screen.findByTestId(`decision-${decisionIds.search}`);
    expect(
      within(panel)
        .getAllByRole('columnheader')
        .map((h) => h.textContent),
    ).toEqual(['question', 'jev', 'nimble']);
  });

  test('totals show a dash when no cost is known', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => {
      const d = decision(id);
      d.calls = d.calls.map((c) => ({ ...c, est_cost_usd: null }));
      return d;
    });
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} />, client);
    await openTurn('search the long gallery');
    await screen.findByTestId(`decision-${decisionIds.search}`);
    expect(screen.getByTestId('totals-jev')).toHaveTextContent('1 calls · – · mean');
  });

  test('a decision id shared by two turns is counted once', async () => {
    const client = fakeApi();
    client.gameDecision.mockImplementation(async (_game, id) => decision(id));
    const shared = turns.map((t, i) => (i < 2 ? { ...t, decisionIds: [decisionIds.search] } : t));
    renderWithApp(<TraceDrawer game="g1" turns={shared} health={healthOn} />, client);
    await openTurn('search the long gallery');
    await screen.findByTestId(`decision-${decisionIds.search}`);
    await waitFor(() => expect(screen.getByTestId('totals-jev')).toHaveTextContent('1 calls'));
  });

  test.each([
    [new ApiError(500, 'internal', 'boom'), 'boom'],
    [new ApiError(404, 'unknown_game', 'nope'), 'nope'],
  ])('a non-retryable error is asked once and shown (%s)', async (error, text) => {
    const client = fakeApi();
    client.gameDecision.mockRejectedValue(error);
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} retryBaseMs={1} />, client);
    await openTurn('search the long gallery');
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(client.gameDecision).toHaveBeenCalledTimes(1);
  });

  test('the drawer reads decisions through the game endpoint, never the admin one', async () => {
    const client = fakeApi();
    client.gameDecision.mockResolvedValue(decision('d1', ['search', 'search']));
    renderWithApp(<TraceDrawer turns={turns} health={healthOn} game="g1" />, client);
    await openTurn('search');
    await screen.findByTestId('decision-d1');
    expect(client.gameDecision).toHaveBeenCalledWith('g1', expect.any(String));
    expect(client.decision).not.toHaveBeenCalled();
  });

  test('a decision outside the transcript says it is not available, and is asked once', async () => {
    const client = fakeApi();
    client.gameDecision.mockRejectedValue(new ApiError(404, 'not_found', 'no such decision'));
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} retryBaseMs={1} />, client);
    await openTurn('search the long gallery');
    expect(await screen.findByText(/not available/)).toBeInTheDocument();
    expect(screen.queryByText(/no such decision/)).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(client.gameDecision).toHaveBeenCalledTimes(1);
  });

  test('a non-API failure shows a generic message, not the raw one', async () => {
    const client = fakeApi();
    client.gameDecision.mockRejectedValue(new TypeError('secret internals'));
    renderWithApp(<TraceDrawer game="g1" turns={turns} health={healthOn} retryBaseMs={1} />, client);
    await openTurn('search the long gallery');
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByText(/secret internals/)).not.toBeInTheDocument();
  });
});

describe('DecisionTable, redacted', () => {
  test('a decision with no preview shows no preview block', () => {
    const d = decision('p', ['search', 'search']);
    d.state_preview = '';
    render(<DecisionTable decision={d} backends={[]} />);
    expect(screen.queryByText('state preview')).not.toBeInTheDocument();
  });

  test('a failed call is shown neutrally, with no detail', () => {
    const d = decision('f', ['search', 'search']);
    d.calls[1]!.error = 'failed';
    render(<DecisionTable decision={d} backends={[]} />);
    expect(screen.getByText('this call failed')).toBeInTheDocument();
    expect(screen.queryByText(/error: failed/)).not.toBeInTheDocument();
  });
});
