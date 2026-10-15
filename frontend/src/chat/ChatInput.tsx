import { type FormEvent, type RefObject, useState } from 'react';
import { StampButton } from '../ui/Button';

interface Props {
  draft: string;
  onDraft: (text: string) => void;
  onSend: (text: string) => void;
  busy: boolean;
  closed: boolean;
  maxChars: number;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
}

/** The typewriter slip. Enter sends, Shift+Enter breaks the line. Disabled while a turn runs. */
export function ChatInput({ draft, onDraft, onSend, busy, closed, maxChars, inputRef }: Props) {
  const [composing, setComposing] = useState(false);
  const disabled = busy || closed;
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (disabled || draft.trim() === '') return;
    onSend(draft);
    onDraft('');
  };
  return (
    <form onSubmit={submit} className="border-t border-ink bg-card p-2">
      {busy && (
        <p role="status" className="mb-1 text-xs italic">
          The agent is typing…
        </p>
      )}
      <textarea
        ref={inputRef}
        aria-label="Message"
        className="h-20 w-full resize-none border border-ink bg-card-light p-2 disabled:opacity-50"
        value={draft}
        maxLength={maxChars}
        disabled={disabled}
        placeholder={closed ? 'The case is closed.' : 'Ask, search, accuse…'}
        onChange={(e) => onDraft(e.target.value)}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !composing) submit(e);
        }}
      />
      <div className="mt-1 flex items-center justify-between text-xs">
        <span>
          {draft.length}/{maxChars}
        </span>
        <StampButton type="submit" disabled={disabled || draft.trim() === ''}>
          Send
        </StampButton>
      </div>
    </form>
  );
}
