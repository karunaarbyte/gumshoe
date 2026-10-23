import { getAdminToken } from './adminToken';
import { ApiError, NETWORK, errorFrom } from './errors';
import { readEvents } from './sse';
import type {
  ConfirmBody,
  DecisionView,
  DisagreementParams,
  GameCreated,
  GameState,
  GameSummary,
  Health,
  Meta,
  SaveSummary,
  StatsParams,
  StatsReport,
  TurnBody,
  TurnEvent,
  TurnRecord,
} from './types';

const JSON_HEADERS = { 'content-type': 'application/json' };

/** `admin` adds the stored admin token as a bearer header; only the admin calls pass it. */
async function send(path: string, init: RequestInit = {}, admin = false): Promise<Response> {
  const token = admin ? getAdminToken() : null;
  const headers = token === null ? init.headers : { ...(init.headers as Record<string, string> | undefined), authorization: `Bearer ${token}` };
  let response: Response;
  try {
    response = await fetch(path, headers === init.headers ? init : { ...init, headers });
  } catch {
    throw new ApiError(0, NETWORK, 'the server could not be reached');
  }
  if (!response.ok) throw await errorFrom(response);
  return response;
}

async function getJson<T>(path: string, admin = false): Promise<T> {
  return (await (await send(path, {}, admin)).json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  return (await response.json()) as T;
}

/** Opens a turn or confirm stream. Errors before streaming (404, 409, 422, 503) throw here. */
async function openStream(path: string, body: unknown, signal?: AbortSignal): Promise<AsyncGenerator<TurnEvent>> {
  const response = await send(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  if (response.body === null) throw new ApiError(0, NETWORK, 'the turn stream had no body');
  return readEvents(response.body);
}

const g = (game: string) => `/api/games/${encodeURIComponent(game)}`;

export const api = {
  health: () => getJson<Health>('/api/health'),
  meta: () => getJson<Meta>('/api/meta'),
  games: () => getJson<GameSummary[]>('/api/games'),
  saves: () => getJson<SaveSummary[]>('/api/saves'),
  createGame: (seed: number, preset?: string) => postJson<GameCreated>('/api/games', preset === undefined ? { seed } : { seed, preset }),
  loadGame: (name: string) => postJson<GameCreated>('/api/games/load', { name }),
  state: (game: string) => getJson<GameState>(g(game)),
  turns: (game: string) => getJson<TurnRecord[]>(`${g(game)}/turns`),
  save: async (game: string) => (await (await send(`${g(game)}/save`, { method: 'POST' })).json()) as { name: string },
  deleteGame: async (game: string): Promise<void> => {
    await send(g(game), { method: 'DELETE' });
  },
  stats: (params: StatsParams = {}) => {
    const q = new URLSearchParams();
    if (params.since) q.set('since', params.since);
    if (params.includeCold) q.set('include_cold', 'true');
    const query = q.toString();
    return getJson<StatsReport>(`/api/stats/decisions${query === '' ? '' : `?${query}`}`, true);
  },
  disagreements: (params: DisagreementParams = {}) => {
    const q = new URLSearchParams({ disagree: 'true', limit: String(params.limit ?? 20) });
    if (params.node) q.set('node', params.node);
    if (params.question) q.set('question', params.question);
    if (params.since) q.set('since', params.since);
    return getJson<DecisionView[]>(`/api/decisions?${q.toString()}`, true);
  },
  gameDecision: (game: string, id: string) => getJson<DecisionView>(`${g(game)}/decisions/${encodeURIComponent(id)}`),
  /** Admin only (sends the admin token); never from the player UI. */
  decision: (id: string) => getJson<DecisionView>(`/api/decisions/${encodeURIComponent(id)}`, true),
  turn: (game: string, body: TurnBody, signal?: AbortSignal) => openStream(`${g(game)}/turn`, body, signal),
  confirm: (game: string, body: ConfirmBody, signal?: AbortSignal) => openStream(`${g(game)}/confirm`, body, signal),
};

export type Api = typeof api;
