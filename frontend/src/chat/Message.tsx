import { summariseTool } from './toolSummary';
import type { PendingView } from '../api/types';
import type { ChatMessage } from '../game/model';
import { ConfirmCard } from './ConfirmCard';
import { Pickers } from './Pickers';

export interface MessageProps {
  message: ChatMessage;
  pending: PendingView | null;
  busy: boolean;
  /** A clarify from an earlier turn, or any turn while a confirmation waits, must not send. */
  stale?: boolean;
  onSend: (text: string) => void;
  onAnswer: (answer: 'yes' | 'no') => void;
}

function Tag({ children }: { children: string }) {
  return <span className="ml-2 border border-ink px-1 text-[10px] uppercase">{children}</span>;
}

const agentLine = 'my-1 border-l-4 border-ink bg-card px-3 py-2';

export function Message({ message: m, pending, busy, stale = false, onSend, onAnswer }: MessageProps) {
  switch (m.kind) {
    case 'player':
      return (
        <div className="my-2 flex justify-end">
          <p className="max-w-[80%] -rotate-1 border border-ink bg-card-light px-3 py-2 shadow-hard">{m.text}</p>
        </div>
      );
    case 'reply': {
      const e = m.event;
      if (e.source === 'help')
        return (
          <p className={`${agentLine} whitespace-pre-line italic`} data-kind="agent-note">
            {e.text}
          </p>
        );
      return (
        <div className="my-2" data-kind="reply">
          <p className="text-xs font-bold uppercase">
            {e.speaker ?? 'Narrator'}
            {e.source === 'canned' && <Tag>stock line</Tag>}
            {e.degraded && <Tag>degraded</Tag>}
            {e.source === 'unreachable' && <Tag>unavailable</Tag>}
          </p>
          <p className="border border-ink bg-card px-3 py-2">{e.text}</p>
        </div>
      );
    }
    case 'tool': {
      const failed = m.result !== null && !m.result.ok;
      const summary = failed || m.result === null ? null : summariseTool(m.result.data);
      return (
        <details className={`my-1 text-xs ${failed ? 'text-stamp' : 'opacity-80'}`} data-kind="tool" open={summary !== null}>
          <summary>
            CASE FILE: {m.call.tool}
            {m.result === null ? ' …' : failed ? ` failed: ${m.result.message ?? m.result.code ?? 'error'}` : ' ok'}
          </summary>
          {summary !== null && (
            <div className="my-1 border-l-4 border-ink bg-card px-3 py-2 text-sm opacity-100" data-kind="tool-summary">
              <p className="font-bold">{summary.heading}</p>
              {summary.lines.map((line, i) => (
                <p key={`${i}-${line}`}>{line}</p>
              ))}
            </div>
          )}
          <details>
            <summary>raw data</summary>
            <pre className="overflow-x-auto whitespace-pre-wrap">{JSON.stringify({ args: m.call.args, result: m.result?.data ?? null }, null, 1)}</pre>
          </details>
        </details>
      );
    }
    case 'clarify':
      return (
        <div className={agentLine} data-kind="clarify">
          <p className="whitespace-pre-line">{m.event.text}</p>
          {m.event.reason === 'accusation' && m.event.problems.length > 0 && <Pickers problems={m.event.problems} disabled={busy || stale} onPick={onSend} />}
        </div>
      );
    case 'confirm':
      return (
        <ConfirmCard
          text={m.event.text}
          warnings={m.event.warnings}
          kind={m.event.pending}
          state={m.state}
          live={m.state === 'open' && pending?.pending_id === m.event.pending_id}
          disabled={busy}
          onAnswer={onAnswer}
        />
      );
    case 'game_over':
      return (
        <p className="my-2 border-2 border-ink bg-ink px-3 py-2 font-display text-card-light uppercase" data-kind="game-over">
          {m.event.outcome === 'won' ? 'Case closed' : 'File remains open'}
        </p>
      );
  }
}
