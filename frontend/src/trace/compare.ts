import type { CallView, DecisionView } from '../api/types';

/** The questions any call answered, in a stable order. */
export function questionsOf(decision: DecisionView): string[] {
  return [...new Set(decision.calls.flatMap((c) => Object.keys(c.answers)))].sort();
}

/** True when two or more backends answered this question and their verdicts differ. */
export function disagrees(calls: CallView[], question: string): boolean {
  const verdicts = calls.flatMap((c) => {
    const a = c.answers[question];
    return a === undefined ? [] : [a.verdict];
  });
  return verdicts.length > 1 && new Set(verdicts).size > 1;
}

export interface BackendTotals {
  backend: string;
  calls: number;
  costUsd: number;
  meanLatencyMs: number | null;
}

/** Running totals per backend over the decisions loaded so far. */
export function totals(decisions: DecisionView[]): BackendTotals[] {
  const by = new Map<string, { calls: number; cost: number; latency: number }>();
  for (const d of decisions) {
    for (const c of d.calls) {
      const t = by.get(c.backend) ?? { calls: 0, cost: 0, latency: 0 };
      t.calls += 1;
      t.cost += c.est_cost_usd ?? 0;
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
