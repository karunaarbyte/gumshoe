// Hand-written mirror of docs/superpowers/specs/2026-10-13-api-contract.md.
// Drift is caught by the fixture-replay tests, not by runtime checks.

export type GameStatus = 'playing' | 'won' | 'lost';
export type Outcome = 'playing' | 'won' | 'lost' | 'gave_up';
export type PendingKind = 'accuse' | 'give_up';

export interface Health {
  status: 'ok';
  game: 'on' | 'off';
  reason: string | null;
  primary: string;
  shadow: string | null;
  persona_models: { default: string; dramatic: string };
  personas: 'up' | 'down'; // down: the dialogue model does not answer, suspects give stock lines
}

export interface Meta {
  presets: string[];
  default_preset: string;
  max_attempts: number;
  max_turn_chars: number;
}

export interface CaseEntry {
  number: number;
  handle: string;
  name: string;
  description: string;
  locked: boolean;
}

export interface RecordKind {
  key: string;
  label: string;
}

export interface PlayerCaseView {
  intro: string;
  locations: CaseEntry[];
  suspects: CaseEntry[];
  record_kinds: RecordKind[];
  attempts_left: number;
  status: GameStatus;
}

export interface NotebookFact {
  handle: string;
  text: string;
  speaker: string | null;
  relates_to: string[]; // suspect display names (CaseEntry.name), not handles
  contradicted: boolean;
}

export interface NotebookSection {
  source: string;
  facts: NotebookFact[];
}

export interface Contradiction {
  lie: string; // fact handle
  exposer: string; // fact handle
  text: string;
}

export interface NotebookView {
  sections: NotebookSection[];
  contradictions: Contradiction[];
}

export interface Reveal {
  culprit: string;
  method: string;
  motive: string;
  secret: string;
}

export interface PendingView {
  pending_id: string;
  kind: PendingKind;
  text: string;
  warnings: string[];
}

export interface GameState {
  brief: PlayerCaseView;
  notebook: NotebookView;
  outcome: Outcome;
  pending: PendingView | null;
  reveal: Reveal | null;
  preset: string | null;
}

export interface GameCreated {
  game: string;
  brief: PlayerCaseView;
  preset: string | null;
}

export interface GameSummary {
  game: string;
  preset: string | null;
  outcome: Outcome;
  attempts_left: number;
  turn_running: boolean;
}

export interface SaveSummary {
  name: string;
  created_at: string;
  pack: string;
  status: GameStatus;
}

export interface ProblemOption {
  handle: string;
  name: string;
}

export interface Problem {
  axis: 'who' | 'how' | 'why';
  reason: 'unclear' | 'not_permitted';
  options: ProblemOption[];
}

export interface IntentEvent {
  kind: 'intent';
  decision_id: string;
  intent: string;
  target: string | null;
  confidence: number;
}

export interface ClarifyEvent {
  kind: 'clarify';
  reason: 'low_confidence' | 'bad_target' | 'mismatch' | 'accusation' | 'pending' | 'error';
  text: string;
  decision_id: string | null;
  problems: Problem[];
}

export interface ToolCallEvent {
  kind: 'tool_call';
  tool: string;
  args: Record<string, unknown>;
}

export interface ToolResultEvent {
  kind: 'tool_result';
  tool: string;
  ok: boolean;
  code: string | null;
  message: string | null;
  data: Record<string, unknown> | null;
}

export interface ReplyEvent {
  kind: 'reply';
  speaker: string | null;
  text: string;
  source: 'draft' | 'canned' | 'help' | 'unreachable';
  degraded: boolean;
  violations: string[];
  model: string | null;
  drafts: number;
  latency_ms: number | null;
}

export interface PostCheckEvent {
  kind: 'post_check';
  decision_id: string;
  contradicts_says: number | null;
  claims_guilt_or_blames_other: number | null;
  failed: boolean;
}

export interface ConfirmEvent {
  kind: 'confirm';
  pending: PendingKind;
  pending_id: string;
  text: string;
  warnings: string[];
  decision_id: string | null;
}

export interface CancelledEvent {
  kind: 'cancelled';
}

export interface GameOverEvent {
  kind: 'game_over';
  outcome: 'won' | 'lost' | 'gave_up';
  reveal: Reveal;
}

export interface DoneEvent {
  kind: 'done';
  turn_ms: number | null;
}

export type TurnEvent =
  | IntentEvent
  | ClarifyEvent
  | ToolCallEvent
  | ToolResultEvent
  | ReplyEvent
  | PostCheckEvent
  | ConfirmEvent
  | CancelledEvent
  | GameOverEvent
  | DoneEvent;

export type EventKind = TurnEvent['kind'];

export const EVENT_KINDS: readonly EventKind[] = [
  'intent',
  'clarify',
  'tool_call',
  'tool_result',
  'reply',
  'post_check',
  'confirm',
  'cancelled',
  'game_over',
  'done',
];

export interface TurnRecord {
  turn_id: string;
  kind: 'turn' | 'confirm';
  text: string;
  ts: string;
  events: TurnEvent[];
  complete: boolean;
}

export interface TurnBody {
  text: string;
  pending_id?: string;
}

export interface ConfirmBody {
  pending_id: string;
  answer: 'yes' | 'no';
}

export interface Answer {
  verdict: string;
  confidence: number;
}

export interface CallView {
  backend: string;
  role: string;
  used: boolean;
  cold: boolean;
  latency_ms: number;
  error: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  est_cost_usd: number | null;
  answers: Record<string, Answer>;
}

export interface DecisionView {
  decision_id: string;
  node: string;
  ts: string;
  fallback: boolean;
  state_preview: string;
  calls: CallView[];
}

export interface ErrorBody {
  code: string;
  message: string;
}
