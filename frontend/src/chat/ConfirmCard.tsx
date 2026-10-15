import type { ConfirmEvent, PendingView } from '../api/types';
import type { ConfirmState } from '../game/model';
import { InkButton, StampButton } from '../ui/Button';

interface Props {
  text: string;
  warnings: string[];
  kind: ConfirmEvent['pending'];
  state: ConfirmState;
  /** Yes and No show only when this card is the confirmation the server is holding. */
  live: boolean;
  disabled: boolean;
  onAnswer: (answer: 'yes' | 'no') => void;
}

const TITLE = { accuse: 'Accusation', give_up: 'Give up' } as const;
const YES = { accuse: 'Yes, accuse', give_up: 'Yes, give up' } as const;
const NO = { accuse: 'No, cancel the accusation', give_up: 'No, keep playing' } as const;
const NOTE: Partial<Record<ConfirmState, string>> = {
  cancelled: 'Cancelled',
  answered: 'Answered',
  replaced: 'Replaced',
  closed: 'No longer waiting',
};

export function ConfirmCard({ text, warnings, kind, state, live, disabled, onAnswer }: Props) {
  const struck = state === 'cancelled';
  return (
    <section aria-label={`${TITLE[kind]} confirmation`} data-state={state} className="my-2 border-2 border-stamp bg-card-light p-3 shadow-hard">
      <p className="font-display text-xs tracking-[0.2em] text-stamp uppercase">{TITLE[kind]}: confirm?</p>
      <p className={struck ? 'line-through opacity-60' : ''}>{text}</p>
      {warnings.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm text-stamp">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {live ? (
        <div className="mt-2 flex gap-2">
          <StampButton aria-label={YES[kind]} disabled={disabled} onClick={() => onAnswer('yes')}>
            Yes
          </StampButton>
          <InkButton aria-label={NO[kind]} disabled={disabled} onClick={() => onAnswer('no')}>
            No
          </InkButton>
        </div>
      ) : (
        NOTE[state] !== undefined && <p className="mt-1 text-xs uppercase">{NOTE[state]}</p>
      )}
    </section>
  );
}

/** A pinned card for a confirmation the transcript no longer shows (it fell off the 200-turn
 * window): the waiting `pending` from `GET /api/games/{game}` is the truth. */
export function PinnedConfirm({ pending, disabled, onAnswer }: { pending: PendingView; disabled: boolean; onAnswer: (a: 'yes' | 'no') => void }) {
  return <ConfirmCard text={pending.text} warnings={pending.warnings} kind={pending.kind} state="open" live disabled={disabled} onAnswer={onAnswer} />;
}
