export interface ToolSummary {
  heading: string;
  lines: string[];
}

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
const texts = (v: unknown): string[] =>
  Array.isArray(v) ? v.flatMap((x) => (typeof x === 'object' && x !== null && typeof (x as { text?: unknown }).text === 'string' ? [(x as { text: string }).text] : [])) : [];

const VERB: Record<string, string> = { search: 'You searched', interrogate: 'You questioned', records: 'You checked' };

/** A plain-language account of a successful search, question or records check; null for any
 * tool result we do not recognise (the caller then falls back to the raw data). */
export function summariseTool(data: Record<string, unknown> | null): ToolSummary | null {
  if (data === null || typeof data.kind !== 'string' || typeof data.label !== 'string') return null;
  const verb = VERB[data.kind];
  if (verb === undefined) return null;
  const heading = `${verb} ${data.label}.`;
  const facts = texts(data.new_facts);
  const lines: string[] = [];
  if (data.status === 'locked') lines.push('Not available yet: find out more elsewhere first.');
  else if (data.status === 'nothing_new' || (data.status === 'ok' && facts.length === 0)) lines.push('Nothing new turned up.');
  for (const f of facts) lines.push(`New: ${f}`);
  for (const c of texts(data.contradictions)) lines.push(`Contradiction: ${c}`);
  const opened = strings(data.opened);
  if (opened.length > 0) lines.push(`Worth a look now: ${opened.join(', ')}.`);
  return { heading, lines };
}
