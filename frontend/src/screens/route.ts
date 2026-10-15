import { useCallback, useEffect, useState } from 'react';

export type Route = { name: 'title' } | { name: 'desk'; game: string } | { name: 'stats' };

/** `#/game/<id>` opens a desk, so a page reload reopens the same game; anything else is the title. */
export function parseRoute(hash: string): Route {
  if (hash === '#/stats') return { name: 'stats' };
  const match = /^#\/game\/([^/]+)$/.exec(hash);
  if (match?.[1] !== undefined) {
    try {
      return { name: 'desk', game: decodeURIComponent(match[1]) };
    } catch {
      return { name: 'title' };
    }
  }
  return { name: 'title' };
}

export function routeHash(route: Route): string {
  if (route.name === 'stats') return '#/stats';
  return route.name === 'desk' ? `#/game/${encodeURIComponent(route.game)}` : '#/';
}

export function useRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const go = useCallback((next: Route) => {
    window.location.hash = routeHash(next);
    setRoute(next);
  }, []);
  return [route, go];
}
