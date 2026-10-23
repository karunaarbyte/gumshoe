import { useQuery } from '@tanstack/react-query';
import type { Api } from '../api/client';
import { isApiError } from '../api/errors';
import { useApi } from './ApiContext';

export const keys = {
  stats: (since: string | undefined, includeCold: boolean) => ['stats', since ?? '', includeCold] as const,
  disagreements: (node: string, question: string, since: string | undefined) => ['disagreements', node, question, since ?? ''] as const,
  health: ['health'] as const,
  meta: ['meta'] as const,
  saves: ['saves'] as const,
  games: ['games'] as const,
  decision: (game: string, id: string) => ['decision', game, id] as const,
};

export function useHealth() {
  const client = useApi();
  // polled, so a model server that stops or returns mid-session shows in the chat column
  return useQuery({ queryKey: keys.health, queryFn: client.health, refetchInterval: 15_000 });
}

export function useMeta() {
  const client = useApi();
  return useQuery({ queryKey: keys.meta, queryFn: client.meta, staleTime: Infinity });
}

export function useSaves() {
  const client = useApi();
  return useQuery({ queryKey: keys.saves, queryFn: client.saves });
}

export function useGames() {
  const client = useApi();
  return useQuery({ queryKey: keys.games, queryFn: client.games });
}

export const DECISION_RETRIES = 4;
export const DECISION_RETRY_BASE_MS = 300;

/** The player's read of one decision: always the game-scoped endpoint, never the admin one. */
export function decisionQuery(client: Api, game: string, id: string) {
  return { queryKey: keys.decision(game, id), queryFn: () => client.gameDecision(game, id), staleTime: Infinity };
}

/** One decision. `not_recorded_yet` is retried a few times with a short backoff (the primary's
 * row can land a moment after its event); every other error is final. */
export function useDecision(game: string, id: string, retryBaseMs: number = DECISION_RETRY_BASE_MS) {
  const client = useApi();
  return useQuery({
    ...decisionQuery(client, game, id),
    retry: (failures, error) => isApiError(error, 'not_recorded_yet') && failures < DECISION_RETRIES,
    retryDelay: (attempt) => retryBaseMs * 2 ** attempt,
  });
}

/** The comparison report. The filters are part of the key, so changing one asks again. */
export function useStats(since: string | undefined, includeCold: boolean) {
  const client = useApi();
  return useQuery({
    queryKey: keys.stats(since, includeCold),
    queryFn: () => client.stats({ since, includeCold }),
  });
}

/** The latest decisions where the backends differ (on one question when given). */
export function useDisagreements(node: string, question: string, since: string | undefined) {
  const client = useApi();
  return useQuery({
    queryKey: keys.disagreements(node, question, since),
    queryFn: () => client.disagreements({ node: node || undefined, question: question || undefined, since }),
  });
}
