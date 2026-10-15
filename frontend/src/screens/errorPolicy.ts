import type { ApiError } from '../api/errors';

export type ErrorAction =
  | { kind: 'off'; message: string }
  | { kind: 'ended' }
  | { kind: 'notice'; message: string }
  | { kind: 'toast'; message: string };

export const ENDED_MESSAGE = 'This game has ended (the server may have restarted).';
export const UNREACHABLE_MESSAGE = 'The game server could not be reached.';

/** What the UI does with an API error (spec section 7). */
export function classify(error: ApiError): ErrorAction {
  switch (error.code) {
    case 'unavailable':
      return { kind: 'off', message: error.message };
    case 'unknown_game':
      return { kind: 'ended' };
    case 'turn_in_progress':
      return { kind: 'notice', message: 'A turn is already running for this game.' };
    case 'network':
      return { kind: 'toast', message: UNREACHABLE_MESSAGE };
    default:
      return { kind: 'toast', message: error.message };
  }
}
