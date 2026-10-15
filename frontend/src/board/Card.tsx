import { motion } from 'framer-motion';
import { type PointerEvent, useState } from 'react';
import { Chip } from '../ui/Button';
import { usePrefersReducedMotion } from '../ui/motion';
import type { BoardCard } from './cards';
import { CARD_H, CARD_W, type Placement } from './layout';

interface Props {
  card: BoardCard;
  /** The id the DOM carries: the card's own id, or an opaque key while it is locked. */
  domKey: string;
  at: Placement;
  onGrab: (card: BoardCard, event: PointerEvent<HTMLElement>) => void;
  onPin: (card: BoardCard, event: PointerEvent<HTMLElement>) => void;
}

/** One index card. A locked card lies face down and flips over when it unlocks. */
export function Card({ card, domKey, at, onGrab, onPin }: Props) {
  const still = usePrefersReducedMotion();
  // flip only a card that was face down when it was first drawn and has since unlocked
  const [startedLocked] = useState(card.locked);
  const flip = !still && startedLocked && !card.locked;
  const face = card.type === 'record' ? 'bg-card-light' : 'bg-card';
  return (
    <div
      data-card-id={domKey}
      data-testid={`card-${domKey}`}
      data-flipped={flip}
      className="absolute touch-none select-none"
      style={{ left: at.x, top: at.y, width: CARD_W, height: CARD_H, transform: `rotate(${at.rotate}deg)`, perspective: 600 }}
      onPointerDown={(e) => onGrab(card, e)}
    >
      <motion.article
        key={card.locked ? 'down' : 'up'}
        initial={flip ? { rotateY: 180 } : false}
        animate={{ rotateY: 0 }}
        transition={{ duration: 0.6 }}
        aria-label={card.locked ? `${card.label}, locked` : `${card.label}: ${card.title}`}
        className={`relative h-full w-full overflow-hidden border border-ink p-2 shadow-hard ${card.locked ? 'bg-ink/80' : face}`}
      >
        <button
          type="button"
          aria-label={card.locked ? `Pin on ${card.label.toLowerCase()}, locked` : `Pin on ${card.label.toLowerCase()} ${card.type === 'fact' ? card.body : card.title}`}
          className="absolute top-1 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full border border-ink bg-stamp"
          onPointerDown={(e) => {
            e.stopPropagation();
            onPin(card, e);
          }}
        />
        <div className="mt-2">
          <Chip>{card.label}</Chip>
        </div>
        {card.locked ? (
          <p className="mt-3 font-display text-lg tracking-widest text-card-light">REDACTED</p>
        ) : (
          <>
            <h3 className="mt-1 truncate font-bold uppercase">{card.title}</h3>
            {card.speaker !== null && <p className="text-xs italic">said by {card.speaker}</p>}
            <p className="line-clamp-3 text-xs">{card.body}</p>
          </>
        )}
        {card.contradicted && (
          <span className="absolute right-1 bottom-2 -rotate-12 border-2 border-stamp px-1 font-display text-sm text-stamp">
            CONTRADICTED
          </span>
        )}
      </motion.article>
    </div>
  );
}
