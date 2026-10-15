import { useCallback, useEffect, useRef, useState } from 'react';
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
  // what is already in storage: loading a game never rewrites it
  const saved = useRef(data);
  const loadedGame = useRef(game);
  useEffect(() => {
    if (loadedGame.current === game) return;
    loadedGame.current = game;
    const loaded = loadBoard(gameKey(game));
    saved.current = loaded;
    setData(loaded);
  }, [game]);
  useEffect(() => {
    if (data === saved.current) return;
    saved.current = data;
    storeBoard(gameKey(game), data);
  }, [data, game]);
  const update = useCallback((change: (d: BoardData) => BoardData) => setData(change), []);
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
