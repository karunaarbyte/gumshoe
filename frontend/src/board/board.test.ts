import { describe, expect, test } from 'vitest';
import { states } from '../test/fixtures';
import { buildCards, factCard, gameStrings, locationCard, suspectCard } from './cards';
import { CARD_H, CARD_W, boardSize, initialLayout, placeCards } from './layout';
import { hashString, jitter } from './seed';
import { copyBoard, gameKey, loadBoard, saveKey, storeBoard } from './storage';
import { addThread, removeThread } from './threads';

const state = states[2]!;
const S1 = suspectCard('Mr Grey the butler');
const S3 = suspectCard('Dr Wren the physician');
const F1 = factCard('Long gallery', 'A stained glass lies by the body.');
const F2 = factCard('Mr Grey the butler', 'He was in the pantry all evening.');
const F3 = factCard('Letters', 'The cook saw Grey in the gallery at nine.');

describe('seed', () => {
  test('hashString is stable and spreads', () => {
    expect(hashString('suspect:s1')).toBe(hashString('suspect:s1'));
    expect(hashString('suspect:s1')).not.toBe(hashString('suspect:s2'));
  });

  test('jitter stays in range', () => {
    for (const k of ['a', 'b', 'fact:f1', 'suspect:s3']) {
      expect(Math.abs(jitter(k, 'r', 2))).toBeLessThanOrEqual(2);
    }
  });
});

describe('cards', () => {
  test('one card per suspect, place, record kind and fact', () => {
    const cards = buildCards(state);
    expect(cards.map((c) => c.type)).toEqual(['suspect', 'suspect', 'suspect', 'location', 'location', 'record', 'record', 'fact', 'fact', 'fact']);
    expect(cards.find((c) => c.id === S3)?.locked).toBe(true);
    expect(cards.find((c) => c.id === F2)).toMatchObject({ contradicted: true, speaker: 'Mr Grey the butler' });
  });

  test('the same text twice in one section is one card', () => {
    const section = state.notebook.sections.find((x) => x.facts.length > 0)!;
    const doubled = { ...state, notebook: { ...state.notebook, sections: state.notebook.sections.map((x) => (x === section ? { ...x, facts: [...x.facts, x.facts[0]!] } : x)) } };
    const ids = buildCards(doubled).map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('the starting layout never overlaps two cards', () => {
    const at = Object.values(initialLayout(buildCards(state)));
    for (const [i, a] of at.entries()) {
      for (const b of at.slice(i + 1)) {
        const apart = Math.abs(a.x - b.x) >= CARD_W || Math.abs(a.y - b.y) >= CARD_H;
        expect(apart).toBe(true);
      }
    }
  });

  test('game strings: contradictions and relates_to by suspect name', () => {
    expect(gameStrings(state).map((s) => [s.from, s.to, s.kind])).toEqual([
      [F2, F3, 'contradiction'],
      [F1, S1, 'relates'],
      [F3, S1, 'relates'],
      [F3, suspectCard('Mrs Pike the cook'), 'relates'],
    ]);
  });

  test('card ids survive a load, which renames every handle', () => {
    const renamed = {
      ...state,
      brief: { ...state.brief, suspects: state.brief.suspects.map((x) => ({ ...x, handle: `new-${x.handle}` })) },
      notebook: {
        sections: state.notebook.sections.map((sec) => ({ ...sec, facts: sec.facts.map((f) => ({ ...f, handle: `new-${f.handle}` })) })),
        contradictions: state.notebook.contradictions.map((c) => ({ ...c, lie: `new-${c.lie}`, exposer: `new-${c.exposer}` })),
      },
    };
    expect(buildCards(renamed).map((c) => c.id)).toEqual(buildCards(state).map((c) => c.id));
    expect(gameStrings(renamed)).toEqual(gameStrings(state));
  });

  test('a contradiction naming a fact not on the board draws nothing', () => {
    const odd = { ...state, notebook: { ...state.notebook, contradictions: [{ lie: 'zz', exposer: 'f3', text: '' }] } };
    expect(gameStrings(odd).filter((s) => s.kind === 'contradiction')).toEqual([]);
  });
});

describe('layout', () => {
  test('is deterministic', () => {
    expect(initialLayout(buildCards(state))).toEqual(initialLayout(buildCards(state)));
  });

  test('suspects sit above places, places above evidence', () => {
    const p = initialLayout(buildCards(state));
    expect(p[S1]!.y).toBeLessThan(p[locationCard('Long gallery')]!.y);
    expect(p[locationCard('Long gallery')]!.y).toBeLessThan(p[F1]!.y);
  });

  test('tilt stays within two degrees', () => {
    for (const p of Object.values(initialLayout(buildCards(state)))) expect(Math.abs(p.rotate)).toBeLessThanOrEqual(2);
  });

  test('a card keeps its place when another card appears', () => {
    const before = initialLayout(buildCards(states[0]!));
    const after = initialLayout(buildCards(state));
    expect(after[S1]).toEqual(before[S1]);
  });

  test('a dragged position overrides the layout, keeping the tilt', () => {
    const cards = buildCards(state);
    const placed = placeCards(cards, { [F1]: { x: 5, y: 6 }, 'fact:gone': { x: 1, y: 1 } });
    expect(placed[F1]).toMatchObject({ x: 5, y: 6, rotate: initialLayout(cards)[F1]!.rotate });
    expect(placed['fact:gone']).toBeUndefined();
  });

  test('the board is big enough for every card', () => {
    const size = boardSize(initialLayout(buildCards(state)));
    expect(size.width).toBeGreaterThan(500);
    expect(size.height).toBeGreaterThan(300);
  });
});

describe('threads', () => {
  test('no thread to itself, one per pair', () => {
    let t = addThread([], 'a', 'b');
    t = addThread(t, 'b', 'a');
    t = addThread(t, 'a', 'a');
    expect(t).toEqual([{ id: 'a~b', from: 'a', to: 'b' }]);
    expect(removeThread(t, 'a~b')).toEqual([]);
  });
});

describe('storage', () => {
  test('keys are per game and per save name', () => {
    expect(gameKey('g1')).toBe('gumshoe:board:game:g1');
    expect(saveKey('0123456789abcdef')).toBe('gumshoe:board:save:0123456789abcdef');
  });

  test('round trip, and an unreadable entry reads empty', () => {
    storeBoard(gameKey('g1'), { positions: { 'fact:f1': { x: 1, y: 2 } }, threads: [{ id: 'a~b', from: 'a', to: 'b' }] });
    expect(loadBoard(gameKey('g1')).positions['fact:f1']).toEqual({ x: 1, y: 2 });
    window.localStorage.setItem(gameKey('bad'), '{not json');
    expect(loadBoard(gameKey('bad'))).toEqual({ positions: {}, threads: [] });
    window.localStorage.setItem(gameKey('odd'), JSON.stringify({ positions: { a: { x: 'no' } }, threads: [1, { id: 'x', from: 'a', to: 'b' }] }));
    expect(loadBoard(gameKey('odd'))).toEqual({ positions: {}, threads: [{ id: 'x', from: 'a', to: 'b' }] });
  });

  test('Save copies the layout under the save name; Load copies it to the new game id', () => {
    storeBoard(gameKey('g1'), { positions: { 'suspect:s1': { x: 9, y: 9 } }, threads: [] });
    copyBoard(gameKey('g1'), saveKey('0123456789abcdef'));
    copyBoard(saveKey('0123456789abcdef'), gameKey('g7'));
    expect(loadBoard(gameKey('g7')).positions['suspect:s1']).toEqual({ x: 9, y: 9 });
  });
});
