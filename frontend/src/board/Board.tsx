import { type PointerEvent, useMemo, useRef, useState } from 'react';
import type { GameState } from '../api/types';
import { Card } from './Card';
import { type BoardCard, buildCards, gameStrings } from './cards';
import { type Point, boardSize, placeCards } from './layout';
import { Strings } from './Strings';
import { useBoard } from './useBoard';

type Gesture =
  | { kind: 'drag'; id: string; start: Point; origin: Point; at: Point }
  | { kind: 'link'; from: string; to: Point };

function boardPoint(el: HTMLElement | null, e: PointerEvent): Point {
  const box = el?.getBoundingClientRect();
  return { x: e.clientX - (box?.left ?? 0) + (el?.scrollLeft ?? 0), y: e.clientY - (box?.top ?? 0) + (el?.scrollTop ?? 0) };
}

/** The card under the pointer. Touch pointers stay captured by the element they started on, so
 * ask the document what is under the finger; fall back to the event target (tests, old engines). */
function cardUnder(e: PointerEvent, ids: Map<string, string>): string | null {
  const hit = typeof document.elementFromPoint === 'function' ? document.elementFromPoint(e.clientX, e.clientY) : null;
  const el = (hit ?? e.target) as Element | null;
  const key = el?.closest?.('[data-card-id]')?.getAttribute('data-card-id');
  return key === undefined || key === null ? null : (ids.get(key) ?? null);
}

/** The corkboard: cards from the game state, red game strings, and the player's own threads. */
export function Board({ game, state }: { game: string; state: GameState }) {
  const board = useBoard(game);
  const cards = useMemo(() => buildCards(state), [state]);
  const strings = useMemo(() => gameStrings(state), [state]);
  const [gesture, setGesture] = useState<Gesture | null>(null);
  // the card being dragged follows the pointer in local state; it is stored once, on release
  const dragAt = gesture?.kind === 'drag' ? gesture : null;
  const placements = useMemo(() => {
    const placed = placeCards(cards, board.data.positions);
    const held = dragAt === null ? undefined : placed[dragAt.id];
    return dragAt !== null && held !== undefined ? { ...placed, [dragAt.id]: { ...held, ...dragAt.at } } : placed;
  }, [cards, board.data.positions, dragAt]);
  // a locked card shows an opaque key in the DOM, never its name; map keys back to card ids
  const keys = useMemo(() => {
    const byCard = new Map<string, string>();
    const byKey = new Map<string, string>();
    cards.forEach((c, i) => {
      const key = c.locked ? `locked-${i}` : c.id;
      byCard.set(c.id, key);
      byKey.set(key, c.id);
    });
    return { byCard, byKey };
  }, [cards]);
  const size = boardSize(placements);
  const ref = useRef<HTMLDivElement>(null);

  const capture = (e: PointerEvent) => {
    try {
      ref.current?.setPointerCapture?.(e.pointerId);
    } catch {
      // capture is best effort; the board still follows the pointer while it is over it
    }
  };
  const grab = (card: BoardCard, e: PointerEvent<HTMLElement>) => {
    const at = placements[card.id];
    if (at === undefined) return;
    setGesture({ kind: 'drag', id: card.id, start: { x: e.clientX, y: e.clientY }, origin: { x: at.x, y: at.y }, at: { x: at.x, y: at.y } });
    capture(e);
  };
  const startLink = (card: BoardCard, e: PointerEvent<HTMLElement>) => {
    capture(e);
    setGesture({ kind: 'link', from: card.id, to: boardPoint(ref.current, e) });
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (gesture === null) return;
    if (e.pointerType === 'mouse' && e.buttons === 0) {
      setGesture(null); // the button went up where we could not see it
      return;
    }
    if (gesture.kind === 'link') {
      setGesture({ ...gesture, to: boardPoint(ref.current, e) });
      return;
    }
    const to = {
      x: Math.max(0, gesture.origin.x + e.clientX - gesture.start.x),
      y: Math.max(0, gesture.origin.y + e.clientY - gesture.start.y),
    };
    setGesture({ ...gesture, at: to });
  };
  const release = (e: PointerEvent<HTMLDivElement>) => {
    if (gesture?.kind === 'link') {
      const target = cardUnder(e, keys.byKey);
      if (target !== null) board.link(gesture.from, target);
    }
    if (gesture?.kind === 'drag' && (gesture.at.x !== gesture.origin.x || gesture.at.y !== gesture.origin.y)) {
      board.move(gesture.id, gesture.at);
    }
    setGesture(null);
  };

  return (
    <div
      ref={ref}
      data-testid="board"
      className="relative h-full w-full overflow-auto bg-paper"
      onPointerMove={move}
      onPointerUp={release}
      onPointerCancel={() => setGesture(null)}
      onLostPointerCapture={() => setGesture(null)}
    >
      <div className="relative" style={{ width: size.width, height: size.height }}>
        <Strings
          width={size.width}
          height={size.height}
          placements={placements}
          strings={strings}
          threads={board.data.threads}
          draft={gesture?.kind === 'link' ? { from: gesture.from, to: gesture.to } : null}
          onCut={board.unlink}
        />
        {cards.map((card) => {
          const at = placements[card.id];
          return at === undefined ? null : <Card key={card.id} card={card} domKey={keys.byCard.get(card.id) ?? card.id} at={at} onGrab={grab} onPin={startLink} />;
        })}
      </div>
    </div>
  );
}
