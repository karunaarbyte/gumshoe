import { useQueries } from '@tanstack/react-query';
import { useState } from 'react';
import type { DecisionView, Health } from '../api/types';
import { useApi } from '../data/ApiContext';
import { keys } from '../data/queries';
import type { TurnView } from '../game/model';
import { InkButton } from '../ui/Button';
import { ms, totals, usd } from './compare';
import { DecisionPanel } from './DecisionPanel';

interface Props {
  turns: TurnView[];
  health: Health | undefined;
  retryBaseMs?: number;
}

function TurnSummary({ turn }: { turn: TurnView }) {
  const intent = turn.events.find((e) => e.kind === 'intent');
  const checks = turn.events.filter((e) => e.kind === 'post_check');
  return (
    <span className="text-xs">
      {intent?.kind === 'intent' && ` · ${intent.intent}${intent.target === null ? '' : ` → ${intent.target}`} (${intent.confidence.toFixed(2)})`}
      {checks.map((c) => c.kind === 'post_check' && (
        <span key={c.decision_id} className={c.failed ? 'text-stamp' : ''}>
          {' '}· check {c.failed ? 'failed' : 'passed'}
        </span>
      ))}
      {turn.turnMs !== null && ` · ${ms(turn.turnMs)}`}
    </span>
  );
}

/** The Jev-versus-Nimble drawer: per turn, newest first, each decision side by side. */
export function TraceDrawer({ turns, health, retryBaseMs }: Props) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const client = useApi();
  const backends = health === undefined ? [] : [health.primary, ...(health.shadow === null ? [] : [health.shadow])];
  const ids = turns.flatMap((t) => t.decisionIds);
  // read-only view of what is already in the cache: these never fetch on their own
  const cached = useQueries({
    queries: ids.map((id) => ({ queryKey: keys.decision(id), queryFn: () => client.decision(id), enabled: false, staleTime: Infinity })),
  });
  const loaded = cached.flatMap((q) => (q.data === undefined ? [] : [q.data as DecisionView]));
  const toggle = (index: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <aside aria-label="Decision trace" className="border-t-2 border-ink bg-card">
      <InkButton className="w-full" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? 'Close the trace' : 'Open the trace'}
      </InkButton>
      {open && (
        <div className="max-h-[45vh] overflow-y-auto p-3">
          <header className="mb-2 flex gap-6 text-xs" aria-label="Totals">
            {totals(loaded).map((t) => (
              <span key={t.backend} data-testid={`totals-${t.backend}`}>
                <b>{t.backend}</b>: {t.calls} calls · {usd(t.costUsd)} · mean {ms(t.meanLatencyMs)}
              </span>
            ))}
            {loaded.length === 0 && <span>No decisions loaded yet. Open a turn.</span>}
          </header>
          <ol>
            {[...turns].reverse().map((t) => (
              <li key={t.index} className="border-b border-ink/30 py-1">
                <button type="button" className="text-left" aria-expanded={expanded.has(t.index)} onClick={() => toggle(t.index)}>
                  <b>#{t.index + 1}</b> “{t.text}”
                </button>
                <TurnSummary turn={t} />
                {expanded.has(t.index) &&
                  (t.decisionIds.length === 0 ? (
                    <p className="text-xs italic">No decisions in this turn.</p>
                  ) : (
                    t.decisionIds.map((id) => <DecisionPanel key={id} id={id} backends={backends} retryBaseMs={retryBaseMs} />)
                  ))}
              </li>
            ))}
          </ol>
        </div>
      )}
    </aside>
  );
}
