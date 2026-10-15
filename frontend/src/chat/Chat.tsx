import { type RefObject, useCallback, useEffect, useRef } from 'react';
import type { GameView } from '../game/model';
import { PinnedConfirm } from './ConfirmCard';
import { ChatInput } from './ChatInput';
import { Message } from './Message';

export interface ChatProps {
  view: GameView;
  busy: boolean;
  maxChars: number;
  draft: string;
  onDraft: (text: string) => void;
  onSend: (text: string) => void | Promise<void>;
  onAnswer: (answer: 'yes' | 'no') => void;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}

export function Chat({ view, busy, maxChars, draft, onDraft, onSend, onAnswer, inputRef }: ChatProps) {
  const end = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  useEffect(() => {
    if (nearBottom.current) end.current?.scrollIntoView?.({ block: 'end' });
  }, [view.messages.length]);
  const pending = view.pending;
  const lastTurn = view.messages.reduce((n, m) => Math.max(n, m.turn), -1);
  const playerCount = view.messages.filter((m) => m.kind === 'player').length;
  const latest = useRef(playerCount);
  latest.current = playerCount;
  const draftRef = useRef(draft);
  draftRef.current = draft;
  // The draft was cleared optimistically; if the send settled and no player message
  // appeared, the turn never started, so put the text back (unless the player typed anew).
  const send = useCallback(
    async (text: string) => {
      const before = latest.current;
      await onSend(text);
      if (latest.current === before && draftRef.current === '') onDraft(text);
    },
    [onSend, onDraft],
  );
  const shown = pending !== null && view.messages.some((m) => m.kind === 'confirm' && m.state === 'open' && m.event.pending_id === pending.pending_id);
  return (
    <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
      <div role="log" aria-label="Case conversation" className="min-h-0 flex-1 overflow-y-auto p-3"
        onScroll={(e) => {
          const t = e.currentTarget;
          nearBottom.current = t.scrollHeight - t.scrollTop - t.clientHeight < 80;
        }}
      >
        {view.messages.map((m) => (
          <Message key={m.id} message={m} pending={pending} busy={busy} stale={m.turn !== lastTurn || pending !== null} onSend={send} onAnswer={onAnswer} />
        ))}
        {pending !== null && !shown && <PinnedConfirm pending={pending} disabled={busy} onAnswer={onAnswer} />}
        {view.status === 'remote' && <p className="text-xs italic">A turn is running…</p>}
        <div ref={end} />
      </div>
      <ChatInput draft={draft} onDraft={onDraft} onSend={send} busy={busy} closed={view.outcome !== 'playing'} maxChars={maxChars} inputRef={inputRef} />
    </section>
  );
}
