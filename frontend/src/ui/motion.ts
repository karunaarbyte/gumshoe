import { useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

function reduced(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches;
}

/** True when the player asked the system for less motion. */
export function usePrefersReducedMotion(): boolean {
  const [value, setValue] = useState(reduced);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const list = window.matchMedia(QUERY);
    const onChange = () => setValue(list.matches);
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, []);
  return value;
}
