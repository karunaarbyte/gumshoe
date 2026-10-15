import { type KeyboardEvent, useEffect, useRef } from 'react';
import { InkButton } from './Button';

const STEPS: [string, string][] = [
  ['The case', 'Someone has been murdered. Your job is to name who did it, how, and why. You have a few attempts, so do not guess.'],
  ['Search places', 'Type "search the Great Hall" in the chat. Every place on the board can be searched, and each search adds facts to your notebook.'],
  ['Meet the suspects', 'Suspects start face down. Searching places and checking records unlocks them one by one. Then ask them questions: "ask Maud the clerk where she was".'],
  ['Check the records', 'Type "show me the household register" (or another record listed in the notebook) to read what the household wrote down.'],
  ['Catch the lies', 'Some suspects lie. A fact that contradicts a claim is marked and joined to it by a red string. Contradictions are your best leads.'],
  ['Use the board', 'Click a card to read it in full. Drag cards to arrange them. Drag from a card’s red pin to another card to draw your own thread. "Tidy up" resets the layout.'],
  ['Accuse', 'When you are ready, press Accuse, or type "I accuse <suspect>". The agent asks for the how and the why; pick the options or answer in your own words, then confirm. A wrong accusation costs an attempt.'],
];

/** A short how-to-play card. Escape or the close button dismisses it. */
export function HelpModal({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => previous?.focus?.();
  }, []);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
    } else if (e.key === 'Tab') {
      e.preventDefault(); // the close button is the only stop
      ref.current?.querySelector<HTMLElement>('button')?.focus();
    }
  };
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label="How to play"
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-ink/70 p-4 outline-none"
    >
      <div className="max-h-full w-full max-w-xl overflow-y-auto border-2 border-ink bg-card-light p-6 shadow-hard">
        <h2 className="mb-4 text-3xl">How to play</h2>
        <ol className="flex flex-col gap-3">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="flex gap-3">
              <span className="font-display text-2xl text-stamp">{i + 1}</span>
              <p>
                <b className="uppercase">{title}.</b> {text}
              </p>
            </li>
          ))}
        </ol>
        <div className="mt-6 flex justify-end">
          <InkButton onClick={onClose}>Got it</InkButton>
        </div>
      </div>
    </div>
  );
}
