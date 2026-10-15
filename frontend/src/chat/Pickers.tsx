import type { Problem } from '../api/types';
import { InkButton } from '../ui/Button';
import { pickerText } from './pickerText';

const AXIS = { who: 'Who', how: 'How', why: 'Why' } as const;

/** One row of buttons per accusation problem; a click sends the option's name as a turn. */
export function Pickers({ problems, disabled, onPick }: { problems: Problem[]; disabled: boolean; onPick: (text: string) => void }) {
  return (
    <div className="mt-2 flex flex-col gap-2">
      {problems.map((p, i) => (
        <div key={`${p.axis}-${i}`} role="group" aria-label={`${AXIS[p.axis]}?`} className="flex flex-wrap items-center gap-2">
          <span className="w-10 font-display text-xs uppercase">{AXIS[p.axis]}</span>
          {p.options.map((o) => (
            <InkButton
              key={o.handle}
              className="px-2 py-1 text-xs normal-case tracking-normal"
              disabled={disabled}
              onClick={() => onPick(pickerText(o, p.axis))}
            >
              {o.name}
            </InkButton>
          ))}
        </div>
      ))}
    </div>
  );
}
