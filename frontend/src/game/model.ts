import type {
  ClarifyEvent,
  ConfirmEvent,
  GameOverEvent,
  GameState,
  Outcome,
  PendingView,
  ReplyEvent,
  Reveal,
  ToolCallEvent,
  ToolResultEvent,
  TurnEvent,
} from '../api/types';

/** idle: input open. running: our stream is open. remote: a turn runs that we are not reading
 * (another tab, a 409, or a reloaded page mid-turn): poll `/turns`. lost: our stream ended
 * without `done`: reload. */
export type TurnStatus = 'idle' | 'running' | 'remote' | 'lost';

/** open: may still be answered. cancelled: struck through. answered: the action ran.
 * replaced: a newer confirmation took its place. closed: the server no longer holds it. */
export type ConfirmState = 'open' | 'cancelled' | 'answered' | 'replaced' | 'closed';

interface Base {
  id: string;
  turn: number;
}

export interface PlayerMessage extends Base {
  kind: 'player';
  text: string;
  via: 'turn' | 'confirm';
}
export interface ReplyMessage extends Base {
  kind: 'reply';
  event: ReplyEvent;
}
export interface ToolMessage extends Base {
  kind: 'tool';
  call: ToolCallEvent;
  result: ToolResultEvent | null;
}
export interface ClarifyMessage extends Base {
  kind: 'clarify';
  event: ClarifyEvent;
}
export interface ConfirmMessage extends Base {
  kind: 'confirm';
  event: ConfirmEvent;
  state: ConfirmState;
}
export interface GameOverMessage extends Base {
  kind: 'game_over';
  event: GameOverEvent;
}

export type ChatMessage = PlayerMessage | ReplyMessage | ToolMessage | ClarifyMessage | ConfirmMessage | GameOverMessage;

export interface TurnView {
  index: number;
  kind: 'turn' | 'confirm';
  text: string;
  ts: string;
  complete: boolean;
  turnMs: number | null;
  decisionIds: string[];
  events: TurnEvent[];
}

export interface GameView {
  game: string;
  state: GameState | null;
  messages: ChatMessage[];
  turns: TurnView[];
  pending: PendingView | null;
  outcome: Outcome;
  reveal: Reveal | null;
  status: TurnStatus;
  nextId: number;
}

export type GameAction =
  | { type: 'turn_started'; kind: 'turn' | 'confirm'; text: string; ts: string }
  | { type: 'event'; event: TurnEvent }
  | { type: 'stream_ended'; sawDone: boolean }
  | { type: 'turn_closed' }
  | { type: 'server_state'; state: GameState }
  | { type: 'remote_running' }
  | { type: 'reset'; view: GameView };

export function emptyView(game: string): GameView {
  return {
    game,
    state: null,
    messages: [],
    turns: [],
    pending: null,
    outcome: 'playing',
    reveal: null,
    status: 'idle',
    nextId: 0,
  };
}
