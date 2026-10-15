import type { ConfirmEvent, PendingView, TurnEvent } from '../api/types';
import type { ChatMessage, ConfirmMessage, ConfirmState, GameAction, GameView, TurnView } from './model';

const SPENDING_TOOLS = new Set(['accuse', 'give_up']);

function withMessage(view: GameView, make: (id: string, turn: number) => ChatMessage): GameView {
  const turn = view.turns.length - 1;
  return {
    ...view,
    messages: [...view.messages, make(`m${view.nextId}`, turn)],
    nextId: view.nextId + 1,
  };
}

function setOpenConfirms(view: GameView, to: ConfirmState, only?: (m: ConfirmMessage) => boolean): GameView {
  let changed = false;
  const messages = view.messages.map((m) => {
    if (m.kind !== 'confirm' || m.state !== 'open' || (only !== undefined && !only(m))) return m;
    changed = true;
    return { ...m, state: to };
  });
  return changed ? { ...view, messages } : view;
}

/** The latest open confirmation card, or -1. */
function latestOpenConfirm(view: GameView): number {
  for (let i = view.messages.length - 1; i >= 0; i -= 1) {
    const m = view.messages[i];
    if (m !== undefined && m.kind === 'confirm' && m.state === 'open') return i;
  }
  return -1;
}

function settleLatestConfirm(view: GameView, to: ConfirmState): GameView {
  const i = latestOpenConfirm(view);
  if (i === -1) return view;
  const messages = view.messages.slice();
  const m = messages[i] as ConfirmMessage;
  messages[i] = { ...m, state: to };
  return { ...view, messages };
}

function updateCurrentTurn(view: GameView, update: (t: TurnView) => TurnView): GameView {
  const last = view.turns[view.turns.length - 1];
  if (last === undefined) return view;
  return { ...view, turns: [...view.turns.slice(0, -1), update(last)] };
}

function decisionIdOf(event: TurnEvent): string | null {
  switch (event.kind) {
    case 'intent':
    case 'post_check':
    case 'clarify':
    case 'confirm':
      return event.decision_id;
    case 'reply':
    case 'tool_call':
    case 'tool_result':
    case 'cancelled':
    case 'game_over':
    case 'done':
      return null;
  }
}

function pendingOf(event: ConfirmEvent): PendingView {
  return {
    pending_id: event.pending_id,
    kind: event.pending,
    text: event.text,
    warnings: event.warnings,
  };
}

function foldEvent(view: GameView, event: TurnEvent): GameView {
  const id = decisionIdOf(event);
  let next = updateCurrentTurn(view, (t) => ({
    ...t,
    events: [...t.events, event],
    decisionIds: id === null || t.decisionIds.includes(id) ? t.decisionIds : [...t.decisionIds, id],
  }));
  switch (event.kind) {
    case 'intent':
    case 'post_check':
      return next; // trace drawer only
    case 'reply':
      return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'reply', event }));
    case 'tool_call':
      if (SPENDING_TOOLS.has(event.tool)) {
        next = settleLatestConfirm(next, 'answered');
        next = { ...next, pending: null };
      }
      return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'tool', call: event, result: null }));
    case 'tool_result': {
      const i = next.messages.findLastIndex((m) => m.kind === 'tool' && m.result === null && m.call.tool === event.tool);
      if (i === -1) {
        const call = { kind: 'tool_call' as const, tool: event.tool, args: {} };
        return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'tool', call, result: event }));
      }
      const messages = next.messages.slice();
      const m = messages[i];
      if (m !== undefined && m.kind === 'tool') messages[i] = { ...m, result: event };
      return { ...next, messages };
    }
    case 'clarify':
      return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'clarify', event }));
    case 'confirm':
      next = setOpenConfirms(next, 'replaced');
      next = { ...next, pending: pendingOf(event) };
      return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'confirm', event, state: 'open' }));
    case 'cancelled':
      return { ...settleLatestConfirm(next, 'cancelled'), pending: null };
    case 'game_over':
      next = setOpenConfirms(next, 'answered');
      next = { ...next, pending: null, outcome: event.outcome, reveal: event.reveal };
      return withMessage(next, (mid, turn) => ({ id: mid, turn, kind: 'game_over', event }));
    case 'done':
      next = updateCurrentTurn(next, (t) => ({ ...t, complete: true, turnMs: event.turn_ms }));
      return { ...next, status: 'idle' };
  }
}

export function gameReducer(view: GameView, action: GameAction): GameView {
  switch (action.type) {
    case 'reset':
      return action.view;
    case 'turn_started': {
      const turn: TurnView = {
        index: view.turns.length,
        kind: action.kind,
        text: action.text,
        ts: action.ts,
        complete: false,
        turnMs: null,
        decisionIds: [],
        events: [],
      };
      const started = { ...view, turns: [...view.turns, turn], status: 'running' as const };
      return withMessage(started, (id, t) => ({ id, turn: t, kind: 'player', text: action.text, via: action.kind }));
    }
    case 'event':
      return foldEvent(view, action.event);
    case 'stream_ended':
      return action.sawDone ? view : { ...view, status: 'lost' };
    case 'turn_closed':
      return { ...updateCurrentTurn(view, (t) => ({ ...t, complete: true })), status: 'idle' };
    case 'remote_running':
      return { ...view, status: 'remote' };
    case 'server_state': {
      const { state } = action;
      const keep = state.pending?.pending_id;
      const closed = setOpenConfirms(view, 'closed', (m) => m.event.pending_id !== keep);
      return {
        ...closed,
        state,
        pending: state.pending,
        outcome: state.outcome,
        reveal: state.reveal,
      };
    }
  }
}
