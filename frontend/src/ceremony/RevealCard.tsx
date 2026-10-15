import type { Reveal } from '../api/types';
import { Chip, InkButton, StampButton } from '../ui/Button';

interface Props {
  reveal: Reveal;
  onNewCase: () => void;
  onClose: () => void;
}

export function RevealCard({ reveal, onNewCase, onClose }: Props) {
  const rows: [string, string][] = [
    ['Culprit', reveal.culprit],
    ['Method', reveal.method],
    ['Motive', reveal.motive],
    ['Secret', reveal.secret],
  ];
  return (
    <article aria-label="The answer" className="w-[520px] rotate-[-1deg] border border-ink bg-card-light p-6 shadow-hard">
      <h2 className="mb-4 text-3xl">The answer</h2>
      <dl className="grid grid-cols-[110px_1fr] gap-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>
              <Chip>{k}</Chip>
            </dt>
            <dd className="font-bold uppercase">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-6 flex gap-3">
        <StampButton onClick={onNewCase}>New case</StampButton>
        <InkButton onClick={onClose}>Back to the board</InkButton>
      </div>
    </article>
  );
}
