import type { BackendStats, NodeStats } from '../api/types';

/** The Wilson score interval for k of n at 95%: honest about small samples (16 of 18 is not 89%). */
export function wilson(k: number, n: number, z = 1.96): [number, number] {
  if (n === 0) return [0, 1];
  const p = k / n;
  const denom = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

export const pct = (rate: number): string => `${Math.round(rate * 100)}%`;

/** "118/165 (72%)": the count and its sample, never a bare rate. */
export function agreementText(rate: number, n: number): string {
  if (n === 0) return 'no decisions';
  return `${Math.round(rate * n)}/${n} (${pct(rate)})`;
}

/** The backend the game used for this node, from its role (names are configuration). */
export const primaryOf = (node: NodeStats): BackendStats | undefined => node.backends.find((b) => b.role === 'primary');

/** The backend that ran beside it, if any. */
export const shadowOf = (node: NodeStats): BackendStats | undefined => node.backends.find((b) => b.role === 'shadow');

/** How much of the node the comparison really covers, and what was left out of it. */
export function comparedLine(node: NodeStats): string {
  const shadow = shadowOf(node)?.backend ?? 'shadow';
  return `${node.compared} of ${node.decisions} decisions compared · ${node.shadow_errors} ${shadow} errors · ${node.fallbacks} fallbacks`;
}

export const timeoutRate = (b: BackendStats): number => (b.calls === 0 ? 0 : b.errors / b.calls);

/** Which way a constant bias runs, so it is not mistaken for disagreement. */
export function offsetText(value: number): string {
  const text = Math.abs(value).toFixed(2);
  if (value > 0.005) return `+${text} (shadow scores higher)`;
  if (value < -0.005) return `-${text} (shadow scores lower)`;
  return '0.00 (no offset)';
}

export function costLabel(b: BackendStats): string {
  if (b.est_cost_usd > 0) return `$${b.est_cost_usd.toFixed(3)}`;
  return `price not set (${b.backend.toUpperCase()}_USD_PER_MTOK_IN/OUT)`;
}

/** A date input's value to the instant it means: local midnight, as UTC. Blank or invalid: none. */
export function sinceToIso(date: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (match === null) return undefined;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const at = new Date(y, m - 1, d);
  at.setFullYear(y); // a year below 100 is not read as 19xx
  // an impossible date (2026-02-31) rolls over: refuse it rather than quietly mean another day
  if (at.getFullYear() !== y || at.getMonth() !== m - 1 || at.getDate() !== d) return undefined;
  return at.toISOString();
}
