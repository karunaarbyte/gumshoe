import { useCallback, useEffect, useState } from 'react';
import type { Point } from './layout';
import { type BoardData, gameKey, loadBoard, storeBoard } from './storage';
import { addThread, removeThread } from './threads';

export interface BoardStore {
  data: BoardData;
  move: (cardId: string, to: Point) => void;
  link: (from: string, to: string) => void;
  unlink: (threadId: string) => void;
}

/** The player's arrangement for one game, kept in localStorage under the game id. */
export function useBoard(game: string): BoardStore {
  const [data, setData] = useState<BoardData>(() => loadBoard(gameKey(game)));
  useEffect(() => setData(loadBoard(gameKey(game))), [game]);
  const update = useCallback(
    (change: (d: BoardData) => BoardData) => {
      setData((current) => {
        const next = change(current);
        if (next !== current) storeBoard(gameKey(game), next);
        return next;
      });
    },
    [game],
  );
  return {
    data,
    move: useCallback((id, to) => update((d) => ({ ...d, positions: { ...d.positions, [id]: to } })), [update]),
    link: useCallback(
      (from, to) =>
        update((d) => {
          const threads = addThread(d.threads, from, to);
          return threads === d.threads ? d : { ...d, threads };
        }),
      [update],
    ),
    unlink: useCallback((id) => update((d) => ({ ...d, threads: removeThread(d.threads, id) })), [update]),
  };
}
