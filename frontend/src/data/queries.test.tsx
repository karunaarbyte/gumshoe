import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient } from '@tanstack/react-query';
import { expect, test } from 'vitest';
import { healthOn, meta } from '../test/fixtures';
import { apiError, fakeApi } from '../test/fakeApi';
import { Providers, testQueryClient } from '../test/render';
import { useDisagreements, useHealth, useMeta, useStats } from './queries';

function wrapper(client = fakeApi()) {
  const queryClient = testQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <Providers client={client} queryClient={queryClient}>
      {children}
    </Providers>
  );
}

test('health and meta come from the injected client', async () => {
  const client = fakeApi();
  const health = renderHook(() => useHealth(), { wrapper: wrapper(client) });
  const m = renderHook(() => useMeta(), { wrapper: wrapper(client) });
  await waitFor(() => expect(health.result.current.data).toEqual(healthOn));
  await waitFor(() => expect(m.result.current.data).toEqual(meta));
});

test('the admin queries never retry on their own, even where the app default would', async () => {
  const client = fakeApi();
  client.stats.mockRejectedValue(apiError('not_found', 404, 'Not Found'));
  client.disagreements.mockRejectedValue(apiError('internal', 500));
  // the app's own defaults (TanStack retries three times unless told otherwise)
  const queryClient = new QueryClient();
  const w = ({ children }: { children: ReactNode }) => (
    <Providers client={client} queryClient={queryClient}>
      {children}
    </Providers>
  );
  const stats = renderHook(() => useStats(undefined, false), { wrapper: w });
  const dis = renderHook(() => useDisagreements('', '', undefined), { wrapper: w });
  await waitFor(() => expect(stats.result.current.isError).toBe(true));
  await waitFor(() => expect(dis.result.current.isError).toBe(true));
  expect(client.stats).toHaveBeenCalledTimes(1);
  expect(client.disagreements).toHaveBeenCalledTimes(1);
});
