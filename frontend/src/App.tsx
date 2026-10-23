import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { useCallback, useState } from 'react';
import { type Api, api as defaultApi } from './api/client';
import type { ApiError } from './api/errors';
import { ApiProvider } from './data/ApiContext';
import { keys, useHealth } from './data/queries';
import type { SessionOptions } from './game/session';
import { Desk } from './screens/Desk';
import { COLD_MESSAGE, ENDED_MESSAGE, classify } from './screens/errorPolicy';
import { GameOff } from './screens/GameOff';
import { useRoute } from './screens/route';
import { StatsPage } from './stats/StatsPage';
import { TitleScreen } from './screens/TitleScreen';
import { ToastProvider, useToast } from './ui/toast';

function Shell({ session }: { session?: Omit<SessionOptions, 'client'> }) {
  const [route, go] = useRoute();
  const [off, setOff] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const health = useHealth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const onError = useCallback(
    (error: ApiError) => {
      const action = classify(error);
      switch (action.kind) {
        case 'off':
          setOff(action.message);
          void queryClient.invalidateQueries({ queryKey: keys.health });
          return;
        case 'ended':
          setBanner(ENDED_MESSAGE);
          void queryClient.invalidateQueries({ queryKey: keys.games });
          go({ name: 'title' });
          return;
        case 'cold':
          setBanner(COLD_MESSAGE);
          void queryClient.invalidateQueries({ queryKey: keys.games });
          go({ name: 'title' });
          return;
        case 'notice':
          toast.show(action.message, 'notice');
          return;
        case 'toast':
          toast.show(action.message, 'error');
      }
    },
    [go, queryClient, toast],
  );

  // the stats read recorded decisions, so they work whether or not the game is on
  if (route.name === 'stats') return <StatsPage onBack={() => go({ name: 'title' })} />;
  if (off !== null) {
    return (
      <GameOff
        reason={health.data?.reason ?? off}
        onRetry={() => {
          setOff(null);
          void health.refetch();
        }}
      />
    );
  }
  if (route.name === 'desk') {
    return <Desk key={route.game} game={route.game} onExit={() => go({ name: 'title' })} onError={onError} session={session} />;
  }
  return (
    <TitleScreen
      banner={banner}
      onError={onError}
      onOpen={(game) => {
        setBanner(null);
        go({ name: 'desk', game });
      }}
    />
  );
}

export const defaultQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { refetchOnWindowFocus: false } },
  });

export function App({ client = defaultApi, queryClient, session }: { client?: Api; queryClient?: QueryClient; session?: Omit<SessionOptions, 'client'> }) {
  const [qc] = useState(() => queryClient ?? defaultQueryClient());
  return (
    <QueryClientProvider client={qc}>
      <ApiProvider client={client}>
        <ToastProvider>
          <MotionConfig reducedMotion="user">
            <Shell session={session} />
          </MotionConfig>
        </ToastProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}
