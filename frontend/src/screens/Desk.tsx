import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { type ApiError, isApiError } from '../api/errors';
import { Board } from '../board/Board';
import { copyBoard, gameKey, hasBoard, saveKey } from '../board/storage';
import { Ceremony } from '../ceremony/Ceremony';
import { Chat } from '../chat/Chat';
import { useApi } from '../data/ApiContext';
import { keys, useHealth, useMeta } from '../data/queries';
import { type SessionHandlers, type SessionOptions, useGameSession } from '../game/session';
import { Notebook } from '../notebook/Notebook';
import { TraceDrawer } from '../trace/TraceDrawer';
import { InkButton } from '../ui/Button';
import { useToast } from '../ui/toast';

interface Props {
  game: string;
  onExit: () => void;
  onError: (error: ApiError) => void;
  session?: Omit<SessionOptions, 'client'>;
}

export const ACCUSE_DRAFT = 'I accuse ';

/** The main screen: notebook | corkboard | chat, with the trace drawer below. */
export function Desk({ game, onExit, onError, session: sessionOptions }: Props) {
  const client = useApi();
  const toast = useToast();
  const queryClient = useQueryClient();
  const health = useHealth();
  const meta = useMeta();
  const handlers = useMemo<SessionHandlers>(() => ({ onError, onNotice: (m) => toast.show(m, 'notice') }), [onError, toast]);
  const session = useGameSession(game, handlers, { ...sessionOptions, client });
  const { view } = session;
  const [draft, setDraft] = useState('');
  const [ceremonyClosed, setCeremonyClosed] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const save = useMutation({
    mutationFn: () => client.save(game),
    onSuccess: ({ name }) => {
      // the arrangement travels with the save name, but never overwrite it with an empty board
      if (hasBoard(gameKey(game))) copyBoard(gameKey(game), saveKey(name));
      toast.show(`Saved as ${name}.`, 'notice');
      void queryClient.invalidateQueries({ queryKey: keys.saves });
    },
    onError: (e) => {
      if (mounted.current && isApiError(e)) onError(e);
    },
  });

  if (!session.ready || view.state === null) {
    return <p className="p-10 font-display text-2xl">Opening the case file…</p>;
  }
  const state = view.state;
  const over = view.outcome !== 'playing';
  const ceremonyOpen = over && view.reveal !== null && !ceremonyClosed;

  return (
    <>
      <div inert={ceremonyOpen} className="grid h-screen grid-rows-[auto_minmax(0,1fr)_auto]">
        <header className="flex items-center gap-4 border-b-2 border-ink bg-card px-4 py-2">
          <h1 className="text-2xl">GUMSHOE</h1>
          <p className="line-clamp-1 flex-1 text-sm italic">{state.brief.intro}</p>
          {over && view.reveal !== null && ceremonyClosed && <InkButton onClick={() => setCeremonyClosed(false)}>Show the answer</InkButton>}
          <InkButton disabled={save.isPending} onClick={() => save.mutate()}>
            Save
          </InkButton>
          <InkButton onClick={onExit}>Case files</InkButton>
        </header>
        {over && view.reveal === null && <p role="status" className="border-b border-ink bg-card-light px-4 py-1 text-sm">This case is closed. The answer is not available for this file.</p>}
        <div className="grid min-h-0 grid-cols-[280px_minmax(0,1fr)_380px]">
          <Notebook
            state={state}
            canAccuse={view.outcome === 'playing' && !session.busy}
            onAccuse={() => {
              setDraft(ACCUSE_DRAFT);
              input.current?.focus();
            }}
          />
          <Board game={game} state={state} />
          <div className="min-h-0 border-l border-ink">
            <Chat
              view={view}
              busy={session.busy}
              maxChars={meta.data?.max_turn_chars ?? 1000}
              draft={draft}
              onDraft={setDraft}
              onSend={(t) => void session.send(t)}
              onAnswer={(a) => void session.answer(a)}
              inputRef={input}
            />
          </div>
        </div>
        <TraceDrawer turns={view.turns} health={health.data} />
      </div>
      {ceremonyOpen && view.reveal !== null && view.outcome !== 'playing' && (
        <Ceremony outcome={view.outcome} reveal={view.reveal} onNewCase={onExit} onClose={() => setCeremonyClosed(true)} />
      )}
    </>
  );
}
