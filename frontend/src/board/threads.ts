export interface Thread {
  id: string;
  from: string; // card id
  to: string; // card id
}

export function threadId(a: string, b: string): string {
  return a < b ? `${a}~${b}` : `${b}~${a}`;
}

/** A new thread between two cards; none to itself, and one per pair whichever way it was drawn. */
export function addThread(threads: Thread[], from: string, to: string): Thread[] {
  if (from === to) return threads;
  const id = threadId(from, to);
  if (threads.some((t) => t.id === id)) return threads;
  return [...threads, { id, from, to }];
}

export function removeThread(threads: Thread[], id: string): Thread[] {
  return threads.filter((t) => t.id !== id);
}
