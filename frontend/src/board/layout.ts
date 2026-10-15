import type { BoardCard } from './cards';
import { jitter } from './seed';

export const CARD_W = 200;
export const CARD_H = 170;
const GAP_X = 36;
const MARGIN = 32;
const ROW_SUSPECTS = 32;
const ROW_PLACES = 242;
const ROW_EVIDENCE = 452;
const FACT_STEP_Y = 190;

export interface Point {
  x: number;
  y: number;
}

export interface Placement extends Point {
  rotate: number; // degrees, -2..2
}

const column = (i: number) => MARGIN + i * (CARD_W + GAP_X);

/** Where each card starts: suspects across the top, places and record kinds below, evidence
 * in one column per source. Jitter and tilt are seeded from the card id, so the same case
 * always lays out the same way. */
export function initialLayout(cards: BoardCard[]): Record<string, Placement> {
  const out: Record<string, Placement> = {};
  const place = (card: BoardCard, x: number, y: number) => {
    out[card.id] = {
      x: Math.round(x + jitter(card.id, 'x', 10)),
      y: Math.round(y + jitter(card.id, 'y', 8)),
      rotate: Math.round(jitter(card.id, 'r', 2) * 10) / 10,
    };
  };
  cards.filter((c) => c.type === 'suspect').forEach((c, i) => place(c, column(i), ROW_SUSPECTS));
  const row2 = cards.filter((c) => c.type === 'location' || c.type === 'record');
  row2.forEach((c, i) => place(c, column(i), ROW_PLACES));
  // evidence hangs under the card it came from (a place, a suspect or a record), one stack each
  const columnOf = new Map<string, number>();
  cards.filter((c) => c.type === 'suspect').forEach((c, i) => columnOf.set(c.title, i));
  row2.forEach((c, i) => columnOf.set(c.title, i));
  let next = Math.max(cards.filter((c) => c.type === 'suspect').length, row2.length);
  const perColumn = new Map<number, number>(); // a suspect and a place can share a column
  for (const c of cards) {
    if (c.type !== 'fact') continue;
    const source = c.source ?? '';
    if (!columnOf.has(source)) columnOf.set(source, next++);
    const col = columnOf.get(source) ?? 0;
    const row = perColumn.get(col) ?? 0;
    perColumn.set(col, row + 1);
    place(c, column(col), ROW_EVIDENCE + row * FACT_STEP_Y);
  }
  return out;
}

/** The layout with the player's dragged positions on top. */
export function placeCards(cards: BoardCard[], moved: Record<string, Point>): Record<string, Placement> {
  const base = initialLayout(cards);
  for (const [id, p] of Object.entries(moved)) {
    const card = base[id];
    if (card !== undefined) base[id] = { ...card, x: p.x, y: p.y };
  }
  return base;
}

export function boardSize(placements: Record<string, Placement>): { width: number; height: number } {
  let width = 0;
  let height = 0;
  for (const p of Object.values(placements)) {
    width = Math.max(width, p.x + CARD_W + MARGIN);
    height = Math.max(height, p.y + CARD_H + MARGIN);
  }
  return { width, height };
}

/** Where a card's pin sits (top centre). */
export function pin(p: Point): Point {
  return { x: p.x + CARD_W / 2, y: p.y + 8 };
}
