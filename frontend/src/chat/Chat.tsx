import { type RefObject, useEffect, useRef } from 'react';
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
  onSend: (text: string) => void;
  onAnswer: (answer: 'yes' | 'no') => void;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}

export function Chat({ view, busy, maxChars, draft, onDraft, onSend, onAnswer, inputRef }: ChatProps) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [view.messages.length]);
  const pending = view.pending;
  const shown = pending !== null && view.messages.some((m) => m.kind === 'confirm' && m.state === 'open' && m.event.pending_id === pending.pending_id);
  return (
    <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
      <div role="log" aria-label="Case conversation" className="min-h-0 flex-1 overflow-y-auto p-3">
        {view.messages.map((m) => (
          <Message key={m.id} message={m} pending={pending} busy={busy} onSend={onSend} onAnswer={onAnswer} />
        ))}
        {pending !== null && !shown && <PinnedConfirm pending={pending} disabled={busy} onAnswer={onAnswer} />}
        {view.status === 'remote' && <p className="text-xs italic">A turn is running…</p>}
        <div ref={end} />
      </div>
      <ChatInput draft={draft} onDraft={onDraft} onSend={onSend} busy={busy} closed={view.outcome !== 'playing'} maxChars={maxChars} inputRef={inputRef} />
    </section>
  );
}
