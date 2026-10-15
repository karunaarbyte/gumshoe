import { InkButton } from '../ui/Button';

/** Full screen: the game endpoints answer 503. */
export function GameOff({ reason, onRetry }: { reason: string | null; onRetry: () => void }) {
  return (
    <main role="alert" aria-label="The game is off" className="flex h-full flex-col items-center justify-center gap-4">
      <h1 className="-rotate-2 border-4 border-stamp px-6 py-2 text-4xl text-stamp">THE GAME IS OFF</h1>
      <p className="max-w-xl text-center">{reason ?? 'The game server is not available right now.'}</p>
      <InkButton onClick={onRetry}>Try again</InkButton>
    </main>
  );
}
