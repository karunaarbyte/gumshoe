import type { ChatMessage } from '../game/model';

/** The agent reads every turn on its own, so a picked how or why sent alone loses the who. While an
 * accusation is being clarified, a pick goes out as the player's last accusation line plus the
 * pick, which is what the agent can parse in one go. Outside that, the pick is sent as it is. */
export function composePick(messages: ChatMessage[], pick: string): string {
  const last = messages[messages.length - 1];
  if (last === undefined || last.kind !== 'clarify' || last.event.reason !== 'accusation') return pick;
  for (let i = messages.length - 2; i >= 0; i -= 1) {
    const m = messages[i]!;
    if (m.kind === 'player') return `${m.text.replace(/[.\s]+$/, '')}. ${pick}`;
  }
  return pick;
}
