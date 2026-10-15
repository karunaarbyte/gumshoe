import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import type { Outcome, Reveal } from '../api/types';
import { colors } from '../theme/tokens';
import { usePrefersReducedMotion } from '../ui/motion';
import { RevealCard } from './RevealCard';

export type Ended = Exclude<Outcome, 'playing'>;

export const stampText = (outcome: Ended) => (outcome === 'won' ? 'CASE CLOSED' : 'FILE REMAINS OPEN');

interface Props {
  outcome: Ended;
  reveal: Reveal;
  onNewCase: () => void;
  onClose: () => void;
  /** Milliseconds for the thread and the stamp; tests shorten them. */
  timing?: { thread: number; stamp: number };
}

type Phase = 'thread' | 'stamp' | 'reveal';

/** Game over: a red thread pulls tight to the culprit's card, a stamp slams down, then the
 * reveal. With reduced motion, the stamp and the reveal card appear at once, still. */
export function Ceremony({ outcome, reveal, onNewCase, onClose, timing = { thread: 900, stamp: 800 } }: Props) {
  const still = usePrefersReducedMotion();
  const [phase, setPhase] = useState<Phase>(still ? 'reveal' : 'thread');
  useEffect(() => {
    if (still) {
      setPhase('reveal');
      return undefined;
    }
    const a = window.setTimeout(() => setPhase('stamp'), timing.thread);
    const b = window.setTimeout(() => setPhase('reveal'), timing.thread + timing.stamp);
    return () => {
      window.clearTimeout(a);
      window.clearTimeout(b);
    };
  }, [still, timing.thread, timing.stamp]);

  return (
    <div role="dialog" aria-modal="true" aria-label="Case result" className="fixed inset-0 z-40 flex flex-col items-center justify-center gap-6 bg-ink/70">
      {!still && (
        <div className="relative h-40 w-[520px]" data-testid="ceremony-stage">
          <svg className="absolute inset-0" width={520} height={160} aria-hidden="true">
            <motion.line
              x1={0}
              y1={150}
              x2={330}
              y2={60}
              stroke={colors.stamp}
              strokeWidth={3}
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: timing.thread / 1000 }}
            />
          </svg>
          <div className="absolute top-6 left-[330px] w-44 rotate-2 border border-ink bg-card p-2 shadow-hard">
            <p className="text-[10px] uppercase">Suspect</p>
            <p className="font-bold uppercase">{reveal.culprit}</p>
          </div>
        </div>
      )}
      {(still || phase !== 'thread') && (
        <motion.p
          role="status"
          className="border-4 border-stamp bg-card-light px-6 py-2 font-display text-4xl text-stamp"
          initial={still ? false : { scale: 2.4, opacity: 0, rotate: -12 }}
          animate={{ scale: 1, opacity: 1, rotate: -6 }}
          transition={{ type: 'spring', stiffness: 500, damping: 18 }}
        >
          {stampText(outcome)}
        </motion.p>
      )}
      {phase === 'reveal' && <RevealCard reveal={reveal} onNewCase={onNewCase} onClose={onClose} />}
    </div>
  );
}
