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
  /** Click to read the whole card: it grows over its neighbours until clicked again. */
  expanded?: boolean;
}

/** One index card. A locked card lies face down and flips over when it unlocks. */
export function Card({ card, domKey, at, onGrab, onPin, expanded = false }: Props) {
  const open = expanded && !card.locked;
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
      data-expanded={open}
      className="absolute touch-none select-none"
      style={{
        left: at.x,
        top: at.y,
        // open: only as big as the text needs, between the closed width and a readable maximum
        ...(open ? { width: 'max-content', minWidth: CARD_W, maxWidth: 300 } : { width: CARD_W, height: CARD_H }),
        zIndex: open ? 30 : undefined,
        transform: `rotate(${open ? 0 : at.rotate}deg)`,
        perspective: 600,
      }}
      onPointerDown={(e) => {
        if (e.button > 0) return; // primary button, touch or pen only
        onGrab(card, e);
      }}
    >
      <motion.article
        key={card.locked ? 'down' : 'up'}
        initial={flip ? { rotateY: 180 } : false}
        animate={{ rotateY: 0 }}
        transition={{ duration: 0.6 }}
        aria-label={card.locked ? `${card.label}${card.revealed ? `: ${card.title}` : ''}, locked` : `${card.label}: ${card.title}`}
        className={`relative ${open ? '' : 'h-full'} w-full overflow-hidden border border-ink p-2 shadow-hard ${card.locked ? 'bg-ink/80' : face}`}
      >
        <button
          type="button"
          aria-label={
            card.locked ? `Pin on ${card.label.toLowerCase()}${card.revealed ? ` ${card.title}, not found yet` : ', locked'}` : `Pin on ${card.label.toLowerCase()} ${card.type === 'fact' ? card.body : card.title}`
          }
          className="absolute top-0 left-1/2 flex h-6 w-6 -translate-x-1/2 items-center justify-center"
          onPointerDown={(e) => {
            e.stopPropagation();
            if (e.button > 0) return;
            onPin(card, e);
          }}
        >
          <span aria-hidden="true" className="h-3 w-3 rounded-full border border-ink bg-stamp" />
        </button>
        <div className="mt-2 flex items-center justify-between">
          <Chip>{card.label}</Chip>
          {card.locked && (
            <span aria-hidden="true" className="text-lg leading-none">
              ❓
            </span>
          )}
        </div>
        {card.locked ? (
          card.revealed ? (
            <>
              <h3 className={`mt-1 ${open ? '' : 'truncate'} font-bold text-card-light uppercase`}>{card.title}</h3>
              <p className="mt-1 font-display text-sm tracking-widest text-card-light">NOT FOUND YET</p>
            </>
          ) : (
            <p className="mt-3 font-display text-lg tracking-widest text-card-light">REDACTED</p>
          )
        ) : (
          <>
            {card.type === 'fact' ? (
              <p className={`mt-1 ${open ? '' : 'truncate'} text-xs font-bold uppercase`}>
                {card.speaker !== null ? `${card.speaker} said` : `Found in ${card.source ?? 'the case'}`}
              </p>
            ) : (
              <h3 className={`mt-1 ${open ? '' : 'truncate'} font-bold uppercase`}>{card.title}</h3>
            )}
            <p className={`${open ? '' : 'line-clamp-1'} text-xs`}>{card.body}</p>
          </>
        )}
        {card.contradicted && (
          <span className="absolute right-1 bottom-2 -rotate-12 border-2 border-stamp px-1 font-display text-sm text-stamp">CONTRADICTED</span>
        )}
      </motion.article>
    </div>
  );
}
