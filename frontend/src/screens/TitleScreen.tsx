import { useMutation, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useState } from 'react';
import { type ApiError, isApiError } from '../api/errors';
import type { GameCreated } from '../api/types';
import { copyBoard, gameKey, saveKey } from '../board/storage';
import { useApi } from '../data/ApiContext';
import { keys, useGames, useHealth, useMeta, useSaves } from '../data/queries';
import { InkButton, StampButton } from '../ui/Button';

interface Props {
  onOpen: (game: string) => void;
  onError: (error: ApiError) => void;
  /** A message to show above everything (for example, the game you had has ended). */
  banner: string | null;
}

const MAX_SEED = Number.MAX_SAFE_INTEGER; // the server takes up to 2^63-1; JSON numbers stay exact to here

/** The seed from the box: empty means random; otherwise a whole number, or null if invalid. */
export function parseSeed(text: string, random: () => number = Math.random): number | null {
  const t = text.trim();
  if (t === '') return Math.floor(random() * 2 ** 31);
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return Number.isSafeInteger(n) && n <= MAX_SEED ? n : null;
}

export function TitleScreen({ onOpen, onError, banner }: Props) {
  const client = useApi();
  const queryClient = useQueryClient();
  const health = useHealth();
  const meta = useMeta();
  const saves = useSaves();
  const games = useGames();
  const [seed, setSeed] = useState('');
  const [preset, setPreset] = useState<string | null>(null);
  const [seedError, setSeedError] = useState<string | null>(null);
  const off = health.data?.game === 'off';
  const fail = (e: unknown) => {
    if (isApiError(e)) onError(e);
  };

  const create = useMutation({
    mutationFn: ({ s, p }: { s: number; p: string }) => client.createGame(s, p),
    onSuccess: (made: GameCreated) => onOpen(made.game),
    onError: fail,
  });
  const load = useMutation({
    mutationFn: (name: string) => client.loadGame(name),
    onSuccess: (made: GameCreated, name: string) => {
      copyBoard(saveKey(name), gameKey(made.game)); // the arrangement saved with it comes back
      onOpen(made.game);
    },
    onError: fail,
  });
  const close = useMutation({
    mutationFn: (game: string) => client.deleteGame(game),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.games }),
    onError: fail,
  });
  const busy = create.isPending || load.isPending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = parseSeed(seed);
    if (s === null) {
      setSeedError('The seed is a whole number (or leave it empty for a random case).');
      return;
    }
    setSeedError(null);
    create.mutate({ s, p: preset ?? meta.data?.default_preset ?? 'standard' });
  };

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 p-10">
      <h1 className="text-6xl">GUMSHOE</h1>
      {banner !== null && (
        <p role="alert" className="border-2 border-stamp bg-card-light p-3 text-stamp">
          {banner}
        </p>
      )}
      {off && (
        <p role="alert" className="border-2 border-ink bg-ink p-3 text-card-light">
          The game is off: {health.data?.reason ?? 'no reason given'}
        </p>
      )}
      <form onSubmit={submit} aria-label="New case" className="flex items-end gap-3 border border-ink bg-card p-4 shadow-hard">
        <label className="flex flex-col text-xs uppercase">
          Seed (optional)
          <input className="border border-ink bg-card-light p-1" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs uppercase">
          Preset
          <select className="border border-ink bg-card-light p-1" value={preset ?? meta.data?.default_preset ?? ''} onChange={(e) => setPreset(e.target.value)}>
            {(meta.data?.presets ?? []).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <StampButton type="submit" disabled={off || busy || meta.data === undefined}>
          New case
        </StampButton>
        {seedError !== null && <p className="text-sm text-stamp">{seedError}</p>}
      </form>
      <section aria-label="Saved games">
        <h2 className="text-2xl">Saved games</h2>
        {saves.data?.length === 0 && <p className="italic">No saves yet.</p>}
        <ul>
          {(saves.data ?? []).map((s) => (
            <li key={s.name} className="flex items-center gap-3 py-1">
              <span className="font-bold">{s.name}</span>
              <span className="text-xs">{new Date(s.created_at).toLocaleString()}</span>
              <span className="text-xs uppercase">{s.status}</span>
              <InkButton disabled={off || busy} onClick={() => load.mutate(s.name)}>
                Load
              </InkButton>
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Open games">
        <h2 className="text-2xl">Open games</h2>
        {games.data?.length === 0 && <p className="italic">No open games.</p>}
        <ul>
          {(games.data ?? []).map((g) => (
            <li key={g.game} className="flex items-center gap-3 py-1">
              <span className="font-bold">{g.preset ?? 'loaded'}</span>
              <span className="text-xs uppercase">{g.outcome}</span>
              <span className="text-xs">attempts left {g.attempts_left}</span>
              {g.turn_running && <span className="text-xs text-stamp">turn running</span>}
              <InkButton disabled={off} onClick={() => onOpen(g.game)}>
                Resume
              </InkButton>
              <InkButton disabled={off || close.isPending} onClick={() => close.mutate(g.game)}>
                Close
              </InkButton>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
