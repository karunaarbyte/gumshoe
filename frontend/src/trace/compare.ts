import type { DecisionView } from '../api/types';

/** The questions any call answered, in a stable order. */
export function questionsOf(decision: DecisionView): string[] {
  return [...new Set(decision.calls.flatMap((c) => Object.keys(c.answers)))].sort();
}

export interface BackendTotals {
  backend: string;
  calls: number;
  costUsd: number | null;
  meanLatencyMs: number | null;
}

/** Running totals per backend over the decisions loaded so far. */
export function totals(decisions: DecisionView[]): BackendTotals[] {
  const by = new Map<string, { calls: number; cost: number | null; latency: number }>();
  for (const d of decisions) {
    for (const c of d.calls) {
      const t = by.get(c.backend) ?? { calls: 0, cost: null, latency: 0 };
      t.calls += 1;
      if (c.est_cost_usd !== null) t.cost = (t.cost ?? 0) + c.est_cost_usd;
      t.latency += c.latency_ms;
      by.set(c.backend, t);
    }
  }
  return [...by.entries()].map(([backend, t]) => ({
    backend,
    calls: t.calls,
    costUsd: t.cost,
    meanLatencyMs: t.calls === 0 ? null : t.latency / t.calls,
  }));
}

export const usd = (v: number | null) => (v === null ? '–' : `$${v.toFixed(v < 0.01 ? 5 : 3)}`);
export const ms = (v: number | null) => (v === null ? '–' : `${Math.round(v)} ms`);
