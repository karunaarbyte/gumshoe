import type { GameState } from '../api/types';

export type CardType = 'suspect' | 'location' | 'fact' | 'record';

export interface BoardCard {
  /** Stable across a save and a load: built from names and text, never from handles, because
   * a loaded game gets new handles (and a new game id). */
  id: string;
  type: CardType;
  label: string; // the chip: SUSPECT, PLACE, EVIDENCE, RECORDS
  title: string;
  body: string;
  locked: boolean;
  contradicted: boolean;
  speaker: string | null;
  source: string | null; // facts: the notebook section
}

export const suspectCard = (name: string) => `suspect:${name}`;
export const locationCard = (name: string) => `location:${name}`;
export const recordCard = (label: string) => `record:${label}`;
export const factCard = (source: string, text: string) => `fact:${source}|${text}`;

/** Every card the board shows, straight from the game state; nothing invented. */
export function buildCards(state: GameState): BoardCard[] {
  const { brief, notebook } = state;
  const base = { contradicted: false, speaker: null, source: null };
  const cards = [
    ...brief.suspects.map((s): BoardCard => ({ ...base, id: suspectCard(s.name), type: 'suspect', label: 'Suspect', title: s.name, body: s.description, locked: s.locked })),
    ...brief.locations.map((l): BoardCard => ({ ...base, id: locationCard(l.name), type: 'location', label: 'Place', title: l.name, body: l.description, locked: l.locked })),
    ...brief.record_kinds.map((r): BoardCard => ({ ...base, id: recordCard(r.label), type: 'record', label: 'Records', title: r.label, body: '', locked: false })),
    ...notebook.sections.flatMap((section) =>
      section.facts.map((f): BoardCard => ({
        id: factCard(section.source, f.text),
        type: 'fact',
        label: 'Evidence',
        title: section.source,
        body: f.text,
        locked: false,
        contradicted: f.contradicted,
        speaker: f.speaker,
        source: section.source,
      })),
    ),
  ];
  // the same text twice in one section is one fact: a card id must be unique on the board
  const seen = new Set<string>();
  return cards.filter((c) => !seen.has(c.id) && seen.add(c.id));
}

export interface GameString {
  id: string;
  from: string; // card id
  to: string; // card id
  kind: 'contradiction' | 'relates';
}

/** The red strings: each contradiction (lie fact to exposer fact), and each fact to the suspects
 * it relates to. `relates_to` holds suspect display names, matched to suspect cards by name. */
export function gameStrings(state: GameState): GameString[] {
  const suspects = new Set(state.brief.suspects.map((s) => s.name));
  const factByHandle = new Map<string, string>();
  for (const section of state.notebook.sections) {
    for (const f of section.facts) factByHandle.set(f.handle, factCard(section.source, f.text));
  }
  const out: GameString[] = [];
  for (const c of state.notebook.contradictions) {
    const from = factByHandle.get(c.lie);
    const to = factByHandle.get(c.exposer);
    if (from !== undefined && to !== undefined) out.push({ id: `c:${from}~${to}`, from, to, kind: 'contradiction' });
  }
  for (const section of state.notebook.sections) {
    for (const f of section.facts) {
      const from = factCard(section.source, f.text);
      for (const name of f.relates_to) {
        if (suspects.has(name)) out.push({ id: `r:${from}~${name}`, from, to: suspectCard(name), kind: 'relates' });
      }
    }
  }
  return out;
}
