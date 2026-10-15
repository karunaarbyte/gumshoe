import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderOptions, render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import type { Api } from '../api/client';
import { ApiProvider } from '../data/ApiContext';
import { ToastProvider } from '../ui/toast';
import { fakeApi } from './fakeApi';

export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

export function Providers({ client, queryClient, children }: { client: Api; queryClient: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </ApiProvider>
    </QueryClientProvider>
  );
}

/** Renders inside the app's providers with a fake API. */
export function renderWithApp(ui: ReactElement, client: Api = fakeApi(), options?: RenderOptions) {
  const queryClient = testQueryClient();
  const result = render(ui, {
    wrapper: ({ children }) => (
      <Providers client={client} queryClient={queryClient}>
        {children}
      </Providers>
    ),
    ...options,
  });
  return { ...result, client, queryClient };
}

/** Makes `prefers-reduced-motion` answer `reduce`. */
export function preferReducedMotion(reduce: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: reduce && query.includes('reduce'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
