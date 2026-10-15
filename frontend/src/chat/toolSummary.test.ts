import { describe, expect, test } from 'vitest';
import { summariseTool } from './toolSummary';

describe('summariseTool', () => {
  test('a search lists the new facts and the places now worth a look', () => {
    const s = summariseTool({ kind: 'search', label: 'Keep', status: 'ok', new_facts: [{ text: 'A rag was thick with wax.' }], contradictions: [{ text: 'Grey lied.' }], opened: ['Maud the clerk'] });
    expect(s).toEqual({
      heading: 'You searched Keep.',
      lines: ['New: A rag was thick with wax.', 'Contradiction: Grey lied.', 'Worth a look now: Maud the clerk.'],
    });
  });

  test('nothing new and locked read plainly', () => {
    expect(summariseTool({ kind: 'search', label: 'Hall', status: 'nothing_new' })?.lines).toEqual(['Nothing new turned up.']);
    expect(summariseTool({ kind: 'interrogate', label: 'Maud', status: 'locked' })?.lines[0]).toMatch(/Not available yet/);
  });

  test('an unknown result has no summary', () => {
    expect(summariseTool(null)).toBeNull();
    expect(summariseTool({ kind: 'mystery', label: 'x' })).toBeNull();
  });
});
