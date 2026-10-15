import { describe, expect, test } from 'vitest';
import { cardIcon } from './icons';

describe('cardIcon', () => {
  test('places and records get a picture from their name', () => {
    expect(cardIcon({ type: 'location', title: 'Chapel of Saint Anne' })).toBe('⛪');
    expect(cardIcon({ type: 'location', title: 'Gatehouse' })).toBe('🚪');
    expect(cardIcon({ type: 'record', title: 'Household register' })).toBe('📖');
  });

  test('suspects get a neutral person, by occupation when the name has one', () => {
    expect(cardIcon({ type: 'suspect', title: 'Roger the priest' })).toBe('🙏');
    expect(cardIcon({ type: 'suspect', title: 'Someone Unknown' })).toBe('🧑');
  });

  test('anything unrecognised falls back to its type', () => {
    expect(cardIcon({ type: 'location', title: 'Moat' })).toBe('🏠');
    expect(cardIcon({ type: 'fact', title: 'Keep' })).toBe('🔎');
  });
});
