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
    expect(summariseTool({ kind: 'interrogate', label: '', status: 'locked' })?.heading).toBe('That is not open to you yet.');
  });

  test('a made accusation reports how many parts were right', () => {
    expect(summariseTool({ status: 'resolved', correct: 0, attempts_left: 2, game: 'playing', message: '0 of 3 right.' })).toEqual({
      heading: 'Your accusation: 0 of 3 right.',
      lines: ['Attempts left: 2.'],
    });
  });

  test('the notebook is a count and the contradictions, not a dump of every fact', () => {
    const s = summariseTool({
      sections: [
        { source: 'Gatehouse', facts: [{ text: 'a' }, { text: 'b' }] },
        { source: 'Kitchen', facts: [{ text: 'c' }] },
      ],
      contradictions: [{ text: 'Grey says pantry, the ledger says hall.' }],
    });
    expect(s).toEqual({
      heading: 'Your notebook: 3 facts from 2 places, 1 contradiction.',
      lines: ['Contradiction: Grey says pantry, the ledger says hall.'],
    });
    expect(summariseTool({ sections: [], contradictions: [] })?.heading).toBe('Your notebook is empty.');
  });

  test('a locked source is redacted: no name, and it says so', () => {
    expect(summariseTool({ kind: 'search', label: '', status: 'locked', new_facts: [] })).toEqual({
      heading: 'That is not open to you yet.',
      lines: ['Keep digging: searching, questioning and reading records open up more.'],
    });
  });

  test('a locked result is redacted even when the label is missing altogether', () => {
    expect(summariseTool({ kind: 'search', status: 'locked' })?.heading).toBe('That is not open to you yet.');
  });

  test('only a real notebook is summarised as one', () => {
    expect(summariseTool({ sections: [], other: 1 })).toBeNull();
  });

  test('an unknown result has no summary', () => {
    expect(summariseTool(null)).toBeNull();
    expect(summariseTool({ kind: 'mystery', label: 'x' })).toBeNull();
  });
});
