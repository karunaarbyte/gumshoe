import type { BoardCard } from "./cards";

// first match wins; a word in the card's title picks the icon. Suspects get neutral person
// icons: the game carries no gender, so none is guessed from a name.
const BY_WORD: Record<BoardCard["type"], [RegExp, string][]> = {
  suspect: [
    [/cook|baker/i, "🧑‍🍳"],
    [/physician|doctor|healer/i, "🧑‍⚕️"],
    [/priest|chaplain|monk|nun/i, "🙏"],
    [/falconer/i, "🦅"],
    [/groom|stable|farmer/i, "🧑‍🌾"],
    [/clerk|scribe|steward/i, "📜"],
    [/bard|minstrel|jester/i, "🎶"],
    [/maid|servant/i, "🧹"],
    [/guard|watchman|knight|soldier/i, "🛡️"],
  ],
  location: [
    [/chapel|church|abbey/i, "⛪"],
    [/kitchen/i, "🍳"],
    [/gatehouse|gate/i, "🚪"],
    [/great hall|hall/i, "🏛️"],
    [/garden|orchard/i, "🌿"],
    [/undercroft|cellar|crypt|dungeon/i, "🕳️"],
    [/keep|tower|castle/i, "🏰"],
    [/armoury|armory|smithy/i, "⚔️"],
    [/stable/i, "🐴"],
    [/library|study/i, "📚"],
  ],
  record: [
    [/register/i, "📖"],
    [/ledger/i, "📒"],
    [/gate log|log/i, "🗒️"],
  ],
  fact: [],
};

const FALLBACK: Record<BoardCard["type"], string> = {
  suspect: "🧑",
  location: "🏠",
  record: "📜",
  fact: "🔎",
};

/** The small picture on a card: a person, a place, a record or a clue, with a more specific one
 * when the card's name says what it is. */
export function cardIcon(card: Pick<BoardCard, "type" | "title">): string {
  const hit = BY_WORD[card.type].find(([word]) => word.test(card.title));
  return hit?.[1] ?? FALLBACK[card.type];
}
