import { type ReactNode, createContext, useContext } from 'react';
import { type Api, api as defaultApi } from '../api/client';

const ApiContext = createContext<Api>(defaultApi);

export function ApiProvider({ client, children }: { client: Api; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  return useContext(ApiContext);
}
