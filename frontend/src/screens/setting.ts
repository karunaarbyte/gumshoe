import type { PackMeta } from '../api/types';

const KEY = 'gumshoe:setting';
const FALLBACK = 'castle';

/** The setting the player chose last time, or null when none is stored or storage is blocked. */
export function readSetting(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function writeSetting(id: string): void {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // blocked or full: the choice is a convenience, the game goes on
  }
}

/** The remembered pack if the server still has it, else the castle, else the first. Never throws on a stale id. */
export function pickSetting(packs: PackMeta[], remembered: string | null): PackMeta {
  return packs.find((p) => p.id === remembered) ?? packs.find((p) => p.id === FALLBACK) ?? packs[0]!;
}
