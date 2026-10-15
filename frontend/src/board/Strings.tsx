import { colors } from '../theme/tokens';
import type { GameString } from './cards';
import { type Placement, pin } from './layout';
import type { Thread } from './threads';

interface Props {
  width: number;
  height: number;
  placements: Record<string, Placement>;
  strings: GameString[];
  threads: Thread[];
  draft: { from: string; to: { x: number; y: number } } | null;
  onCut: (threadId: string) => void;
}

/** Red game strings (pin to pin) and the player's dashed ink threads (clickable to delete). */
export function Strings({ width, height, placements, strings, threads, draft, onCut }: Props) {
  const ends = (from: string, to: string) => {
    const a = placements[from];
    const b = placements[to];
    return a === undefined || b === undefined ? null : { a: pin(a), b: pin(b) };
  };
  const draftFrom = draft === null ? undefined : placements[draft.from];
  return (
    <svg className="pointer-events-none absolute inset-0" width={width} height={height}>
      {strings.map((s) => {
        const e = ends(s.from, s.to);
        if (e === null) return null;
        return <line key={s.id} data-testid="game-string" x1={e.a.x} y1={e.a.y} x2={e.b.x} y2={e.b.y} stroke={colors.stamp} strokeWidth={2} />;
      })}
      {threads.map((t) => {
        const e = ends(t.from, t.to);
        if (e === null) return null;
        return (
          <g key={t.id}>
            <line x1={e.a.x} y1={e.a.y} x2={e.b.x} y2={e.b.y} stroke={colors.ink} strokeWidth={2} strokeDasharray="6 4" />
            <line
              data-testid="player-thread"
              role="button"
              aria-label="Delete thread"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onCut(t.id);
                }
              }}
              className="pointer-events-auto cursor-pointer"
              x1={e.a.x}
              y1={e.a.y}
              x2={e.b.x}
              y2={e.b.y}
              stroke="transparent"
              strokeWidth={12}
              onClick={() => onCut(t.id)}
            />
          </g>
        );
      })}
      {draft !== null && draftFrom !== undefined && (
        <line x1={pin(draftFrom).x} y1={pin(draftFrom).y} x2={draft.to.x} y2={draft.to.y} stroke={colors.ink} strokeWidth={2} strokeDasharray="6 4" />
      )}
    </svg>
  );
}
