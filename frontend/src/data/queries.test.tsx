import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { expect, test } from 'vitest';
import { healthOn, meta } from '../test/fixtures';
import { fakeApi } from '../test/fakeApi';
import { Providers, testQueryClient } from '../test/render';
import { useHealth, useMeta } from './queries';

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
