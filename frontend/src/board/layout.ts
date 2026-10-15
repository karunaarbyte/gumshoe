import type { BoardCard } from './cards';
import { jitter } from './seed';

export const CARD_W = 180;
export const CARD_H = 124;
const GAP_X = 36;
const MARGIN = 32;
const ROW_SUSPECTS = 32;
const ROW_PLACES = 228;
const ROW_EVIDENCE = 424;
const FACT_STEP_Y = 150;

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
  const sources: string[] = [];
  const perSource = new Map<string, number>();
  for (const c of cards) {
    if (c.type !== 'fact') continue;
    const source = c.source ?? '';
    if (!perSource.has(source)) {
      perSource.set(source, 0);
      sources.push(source);
    }
    const row = perSource.get(source) ?? 0;
    perSource.set(source, row + 1);
    place(c, column(sources.indexOf(source)), ROW_EVIDENCE + row * FACT_STEP_Y);
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
