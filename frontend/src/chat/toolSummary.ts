export interface ToolSummary {
  heading: string;
  lines: string[];
}

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);
const texts = (v: unknown): string[] =>
  Array.isArray(v)
    ? v.flatMap((x) => (typeof x === 'object' && x !== null && typeof (x as { text?: unknown }).text === 'string' ? [(x as { text: string }).text] : []))
    : [];

const VERB: Record<string, string> = {
  search: 'You searched',
  interrogate: 'You questioned',
  records: 'You checked',
};

/** A plain-language account of a successful search, question or records check; null for any
 * tool result we do not recognise (the caller then falls back to the raw data). */
export function summariseTool(data: Record<string, unknown> | null): ToolSummary | null {
  if (data !== null && data.status === 'resolved' && typeof data.message === 'string') {
    // a made accusation: how many parts were right, and what is left to try
    const left = typeof data.attempts_left === 'number' ? [`Attempts left: ${data.attempts_left}.`] : [];
    return { heading: `Your accusation: ${data.message}`, lines: left };
  }
  if (data !== null && Array.isArray(data.sections) && Array.isArray(data.contradictions)) {
    // the notebook panel already lists the facts: say how many, and give the contradictions
    const facts = data.sections.reduce<number>((n, sec) => {
      const list = (sec as { facts?: unknown }).facts;
      return n + (Array.isArray(list) ? list.length : 0);
    }, 0);
    const places = data.sections.length;
    const contradictions = texts(data.contradictions);
    const s = (n: number) => (n === 1 ? '' : 's');
    const heading =
      facts === 0
        ? 'Your notebook is empty.'
        : `Your notebook: ${facts} fact${s(facts)} from ${places} place${s(places)}, ${contradictions.length} contradiction${s(contradictions.length)}.`;
    return { heading, lines: contradictions.map((c) => `Contradiction: ${c}`) };
  }
  if (data !== null && data.status === 'locked' && typeof data.kind === 'string') {
    // the name of a locked suspect or place is a secret; the engine sends it empty
    return {
      heading: 'That is not open to you yet.',
      lines: ['Keep digging: searching, questioning and reading records open up more.'],
    };
  }
  if (data === null || typeof data.kind !== 'string' || typeof data.label !== 'string') return null;
  const verb = VERB[data.kind];
  if (verb === undefined) return null;
  const heading = `${verb} ${data.label}.`;
  const facts = texts(data.new_facts);
  const lines: string[] = [];
  if (data.status === 'nothing_new' || (data.status === 'ok' && facts.length === 0)) lines.push('Nothing new turned up.');
  for (const f of facts) lines.push(`New: ${f}`);
  for (const c of texts(data.contradictions)) lines.push(`Contradiction: ${c}`);
  const opened = strings(data.opened);
  if (opened.length > 0) lines.push(`Worth a look now: ${opened.join(', ')}.`);
  return { heading, lines };
}
