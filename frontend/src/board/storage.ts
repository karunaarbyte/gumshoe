import type { Point } from './layout';
import type { Thread } from './threads';

export interface BoardData {
  positions: Record<string, Point>;
  threads: Thread[];
}

const PREFIX = 'gumshoe:board:';
export const gameKey = (game: string) => `${PREFIX}game:${game}`;
export const saveKey = (name: string) => `${PREFIX}save:${name}`;

export const emptyBoard = (): BoardData => ({ positions: {}, threads: [] });

function isPoint(v: unknown): v is Point {
  return typeof v === 'object' && v !== null && Number.isFinite((v as Point).x) && Number.isFinite((v as Point).y);
}

function isThread(v: unknown): v is Thread {
  if (typeof v !== 'object' || v === null) return false;
  const t = v as Record<string, unknown>;
  return typeof t.id === 'string' && typeof t.from === 'string' && typeof t.to === 'string';
}

/** The stored board, or an empty one when nothing (or something unreadable) is stored. */
export function loadBoard(key: string): BoardData {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return emptyBoard();
  }
  if (raw === null) return emptyBoard();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return emptyBoard();
    const { positions, threads } = parsed as Record<string, unknown>;
    const out = emptyBoard();
    if (typeof positions === 'object' && positions !== null) {
      for (const [id, p] of Object.entries(positions)) if (isPoint(p)) out.positions[id] = { x: p.x, y: p.y };
    }
    if (Array.isArray(threads)) out.threads = threads.filter(isThread);
    return out;
  } catch {
    return emptyBoard();
  }
}

export function storeBoard(key: string, data: BoardData): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(data));
  } catch {
    // storage full or blocked: the arrangement is a convenience, the game goes on
  }
}

/** Copies a board under another key (game to save name on Save, save name to game on Load). */
export function copyBoard(fromKey: string, toKey: string): void {
  storeBoard(toKey, loadBoard(fromKey));
}

/** Whether anything is stored under the key (an absent board must not overwrite a copy). */
export function hasBoard(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}
