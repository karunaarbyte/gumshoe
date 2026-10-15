import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { type Api, api as defaultApi } from '../api/client';
import { type ApiError, isApiError } from '../api/errors';
import type { TurnBody, TurnEvent } from '../api/types';
import { emptyView, type GameView } from './model';
import { gameReducer } from './reducer';
import { rebuild } from './rebuild';

export const POLL_MS = 1000;

export interface SessionHandlers {
  /** Any API failure the session does not handle itself (unavailable, unknown_game, toasts). */
  onError: (error: ApiError) => void;
  /** A soft notice: a turn already running, a lost connection. */
  onNotice: (message: string) => void;
}

export interface SessionOptions {
  client?: Api;
  pollMs?: number;
  now?: () => string;
}

export interface Session {
  view: GameView;
  /** False until the first state and transcript have loaded. */
  ready: boolean;
  /** True while the latest load or reload failed; cleared by a successful reload. */
  loadError: boolean;
  /** True from the moment a turn is sent until its stream has ended and state is fresh. */
  busy: boolean;
  send: (text: string) => Promise<void>;
  answer: (answer: 'yes' | 'no') => Promise<void>;
  reload: () => Promise<void>;
}

export const TURN_RUNNING_NOTICE = 'A turn is already running for this game. Waiting for it to finish.';
export const CONNECTION_LOST_NOTICE = 'Connection lost. Reloading the case file.';
export const PENDING_GONE_NOTICE = 'That confirmation is no longer waiting.';

export function useGameSession(game: string, handlers: SessionHandlers, options: SessionOptions = {}): Session {
  // fixed for the life of the session, so an inline options object cannot restart it
  const [client] = useState<Api>(() => options.client ?? defaultApi);
  const [now] = useState(() => options.now ?? (() => new Date().toISOString()));
  const pollMs = options.pollMs ?? POLL_MS;
  const [view, dispatch] = useReducer(gameReducer, game, emptyView);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [sending, setSending] = useState(false);
  const [pollTick, setPollTick] = useState(0);
  const readyRef = useRef(false);
  readyRef.current = ready;
  const viewRef = useRef(view);
  viewRef.current = view;
  const inFlight = useRef(false); // set synchronously: a double click can never send twice
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  // Desk must remount per game (key={game}); the session is bound to one game for life
  const alive = useRef(true);
  const abort = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    try {
      const [state, turns] = await Promise.all([client.state(game), client.turns(game)]);
      if (!alive.current) return;
      dispatch({ type: 'reset', view: rebuild(game, state, turns) });
      setReady(true);
      setLoadError(false);
    } catch (error) {
      if (alive.current) setLoadError(true);
      if (alive.current && isApiError(error)) handlersRef.current.onError(error);
      else if (alive.current) throw error;
    }
  }, [client, game]);

  useEffect(() => {
    alive.current = true;
    reload().catch(() => {
      // a non-API failure on the first load (network down): show the connection-lost notice
      if (alive.current) handlersRef.current.onNotice(CONNECTION_LOST_NOTICE);
    });
    return () => {
      alive.current = false;
      abort.current?.abort();
    };
  }, [reload]);

  // a turn we are not reading (another tab, a 409, a reload mid-turn): poll until it ends
  useEffect(() => {
    if (view.status !== 'remote' && view.status !== 'lost') return undefined;
    const timer = window.setTimeout(() => {
      // success or failure, tick so the effect re-arms while the status stays remote or lost
      reload()
        .catch(() => undefined)
        .finally(() => {
          if (alive.current) setPollTick((t) => t + 1);
        });
    }, pollMs);
    return () => window.clearTimeout(timer);
  }, [view.status, pollTick, pollMs, reload]);

  // a reload inside run() must never reject send()/answer(): non-API failures become a notice
  const safeReload = useCallback(async () => {
    try {
      await reload();
    } catch {
      if (alive.current) handlersRef.current.onNotice(CONNECTION_LOST_NOTICE);
    }
  }, [reload]);

  const run = useCallback(
    async (kind: 'turn' | 'confirm', text: string, open: (signal: AbortSignal) => Promise<AsyncGenerator<TurnEvent>>) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setSending(true);
      const controller = new AbortController();
      abort.current = controller;
      try {
        let events: AsyncGenerator<TurnEvent>;
        try {
          events = await open(controller.signal);
        } catch (error) {
          if (!alive.current) return;
          if (!isApiError(error)) throw error;
          if (error.code === 'turn_in_progress') {
            handlersRef.current.onNotice(TURN_RUNNING_NOTICE);
            dispatch({ type: 'remote_running' });
          } else if (error.code === 'no_such_pending') {
            handlersRef.current.onNotice(PENDING_GONE_NOTICE);
            await safeReload();
          } else {
            handlersRef.current.onError(error);
          }
          return;
        }
        dispatch({ type: 'turn_started', kind, text, ts: now() });
        let sawDone = false;
        try {
          for await (const event of events) {
            if (event.kind === 'done') sawDone = true;
            dispatch({ type: 'event', event });
          }
        } catch {
          sawDone = false; // the connection dropped mid-turn
        }
        if (!alive.current) return;
        dispatch({ type: 'stream_ended', sawDone });
        if (!sawDone) {
          handlersRef.current.onNotice(CONNECTION_LOST_NOTICE);
          await safeReload();
          return;
        }
        try {
          dispatch({ type: 'server_state', state: await client.state(game) });
        } catch (error) {
          if (!alive.current) return;
          if (isApiError(error)) handlersRef.current.onError(error);
        }
      } finally {
        inFlight.current = false;
        if (alive.current) setSending(false);
      }
    },
    [client, game, now, reload, safeReload],
  );

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      const current = viewRef.current;
      if (!readyRef.current || text === '' || current.status !== 'idle' || current.outcome !== 'playing') return;
      const body: TurnBody = { text };
      // a typed yes runs the action only with the waiting id; never send an id otherwise
      if (current.pending !== null) body.pending_id = current.pending.pending_id;
      await run('turn', text, (signal) => client.turn(game, body, signal));
    },
    [client, game, run],
  );

  const answer = useCallback(
    async (choice: 'yes' | 'no') => {
      const current = viewRef.current;
      if (!readyRef.current || current.pending === null || current.status !== 'idle') return;
      const pendingId = current.pending.pending_id;
      await run('confirm', choice, (signal) => client.confirm(game, { pending_id: pendingId, answer: choice }, signal));
    },
    [client, game, run],
  );

  return { view, ready, loadError, busy: sending || view.status !== 'idle', send, answer, reload };
}
