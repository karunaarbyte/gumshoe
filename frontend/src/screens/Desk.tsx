import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { type ApiError, isApiError } from '../api/errors';
import { HelpModal } from '../ui/HelpModal';
import { Board } from '../board/Board';
import { copyBoard, gameKey, hasBoard, removeBoard, saveKey } from '../board/storage';
import { Ceremony } from '../ceremony/Ceremony';
import { Chat } from '../chat/Chat';
import { useApi } from '../data/ApiContext';
import { keys, useHealth, useMeta } from '../data/queries';
import { CONNECTION_LOST_NOTICE, type SessionHandlers, type SessionOptions, useGameSession } from '../game/session';
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
  const saving = useRef(false);
  const [notebookOpen, setNotebookOpen] = useState(() => {
    try {
      return window.localStorage.getItem('gumshoe:notebook') !== 'closed';
    } catch {
      return true;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem('gumshoe:notebook', notebookOpen ? 'open' : 'closed');
    } catch {
      // a per-viewer convenience; the desk works without it
    }
  }, [notebookOpen]);
  const [helpOpen, setHelpOpen] = useState(false);
  const answerButton = useRef<HTMLButtonElement>(null);
  const exitButton = useRef<HTMLButtonElement>(null);
  const focusAfterClose = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // the ceremony hands focus back to a control that is gone or disabled: land on a live one
  useEffect(() => {
    if (ceremonyClosed && focusAfterClose.current) {
      focusAfterClose.current = false;
      (answerButton.current ?? exitButton.current)?.focus();
    }
  }, [ceremonyClosed]);

  const save = useMutation({
    mutationFn: () => client.save(game),
    onSuccess: ({ name }) => {
      // the arrangement travels with the save name; a reused name must not keep an older game's board
      if (hasBoard(gameKey(game))) copyBoard(gameKey(game), saveKey(name));
      else removeBoard(saveKey(name));
      toast.show(`Saved as ${name}.`, 'notice');
      void queryClient.invalidateQueries({ queryKey: keys.saves });
    },
    onSettled: () => {
      saving.current = false;
    },
    onError: (e) => {
      if (mounted.current && isApiError(e)) onError(e);
    },
  });

  if (!session.ready || view.state === null) {
    if (session.loadError) {
      return (
        <div role="alert" className="grid h-screen place-content-center gap-4 p-10 text-center">
          <h1 className="font-display text-3xl">Couldn't open the case file</h1>
          <p>The game server did not answer. Try again, or go back to the case files.</p>
          <div className="flex justify-center gap-3">
            <InkButton onClick={() => void session.reload().catch(() => toast.show(CONNECTION_LOST_NOTICE, 'notice'))}>Retry</InkButton>
            <InkButton onClick={onExit}>Case files</InkButton>
          </div>
        </div>
      );
    }
    return <p className="p-10 font-display text-2xl">Opening the case file…</p>;
  }
  const state = view.state;
  const over = view.outcome !== 'playing';
  const ceremonyOpen = over && view.reveal !== null && !ceremonyClosed;

  return (
    <>
      <div
        inert={ceremonyOpen || helpOpen}
        className={`grid h-screen grid-rows-[minmax(0,1fr)] ${notebookOpen ? 'grid-cols-[280px_minmax(0,1fr)_400px]' : 'grid-cols-[88px_minmax(0,1fr)_400px]'}`}
      >
        <Notebook
          state={state}
          collapsed={!notebookOpen}
          onToggle={() => setNotebookOpen((o) => !o)}
          canAccuse={view.outcome === 'playing' && !session.busy}
          onAccuse={() => {
            if (draft === '') setDraft(ACCUSE_DRAFT);
            input.current?.focus();
          }}
        />
        <div data-testid="desk-main" className="grid min-h-0 min-w-0 grid-rows-[auto_auto_minmax(0,1fr)_auto]">
          <header className="flex items-center gap-4 border-b-2 border-ink bg-card px-4 py-1">
            <h1 className="text-2xl">GUMSHOE</h1>
            <span className="flex-1" />
            {over && view.reveal === null && (
              <p role="status" className="text-sm">
                This case is closed. The answer is not available for this file.
              </p>
            )}
            {over && view.reveal !== null && ceremonyClosed && (
              <InkButton ref={answerButton} onClick={() => setCeremonyClosed(false)}>
                Show the answer
              </InkButton>
            )}
            <InkButton
              className="py-1!"
              disabled={save.isPending}
              onClick={() => {
                if (saving.current) return;
                saving.current = true;
                save.mutate();
              }}
            >
              Save
            </InkButton>
            <InkButton className="py-1!" ref={exitButton} onClick={onExit}>
              Case files
            </InkButton>
          </header>
          <section aria-label="The case" className="border-b-2 border-ink bg-card-light px-6 py-2 text-center">
            <span className="mx-auto mb-2 block w-fit bg-stamp px-4 py-1 font-display text-sm tracking-[0.2em] text-card-light uppercase shadow-hard">
              The case
            </span>
            <p className="mx-auto max-w-4xl font-display text-lg leading-snug">{state.brief.intro}</p>
          </section>
          <div className="min-h-0 min-w-0 overflow-hidden">
            <Board game={game} state={state} />
          </div>
          <TraceDrawer turns={view.turns} health={health.data} />
        </div>
        <aside aria-label="Case chat" className="flex h-screen min-h-0 flex-col border-l-2 border-ink bg-card">
          <div className="flex shrink-0 items-center justify-between border-b border-ink bg-card px-3 py-1">
            <span className="text-xs tracking-widest uppercase">Chat</span>
            <button
              type="button"
              aria-label="How to play"
              title="How to play"
              onClick={() => setHelpOpen(true)}
              className="h-7 w-7 border border-ink bg-card-light font-display text-lg leading-none"
            >
              ?
            </button>
          </div>
          {health.data?.personas === 'down' && (
            <p role="status" className="shrink-0 border-b border-ink bg-card-light px-3 py-1 text-xs italic">
              The dialogue model is offline, so suspects can only give stock lines until it is back.
            </p>
          )}
          {health.data?.mode === 'slow' && (
            <p role="status" className="shrink-0 border-b border-ink bg-card-light px-3 py-1 text-xs italic">
              The detectives are working slowly today.
            </p>
          )}
          {view.queued !== null && (
            <p role="status" className="shrink-0 border-b border-ink bg-card-light px-3 py-1 text-xs italic">
              {view.queued <= 1 ? 'You are next…' : `Waiting for a detective… (${view.queued - 1} ahead)`}
            </p>
          )}
          <div className="min-h-0 flex-1">
            <Chat
              view={view}
              busy={session.busy}
              maxChars={meta.data?.max_turn_chars ?? 1000}
              draft={draft}
              onDraft={setDraft}
              onSend={(t) => session.send(t)}
              onAnswer={(a) => void session.answer(a)}
              inputRef={input}
            />
          </div>
        </aside>
      </div>
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} />}
      {ceremonyOpen && view.reveal !== null && view.outcome !== 'playing' && (
        <Ceremony
          outcome={view.outcome}
          reveal={view.reveal}
          onNewCase={onExit}
          onClose={() => {
            focusAfterClose.current = true;
            setCeremonyClosed(true);
          }}
        />
      )}
    </>
  );
}
