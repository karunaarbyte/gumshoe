import { useState } from 'react';
import { isApiError } from '../api/errors';
import type { NodeStats } from '../api/types';
import { useDisagreements, useStats } from '../data/queries';
import { DecisionTable } from '../trace/DecisionPanel';
import { InkButton } from '../ui/Button';
import { NodeCard } from './NodeCard';
import { pct, shadowOf, sinceToIso } from './summary';

function Definition() {
  return (
    <section aria-label="What agreement means" className="border-2 border-ink bg-card p-3 text-sm">
      <b>Read this first.</b> “Agreement” means the two models gave the same answer to each other, not that either is right: there is no ground truth, and the
      model that decides the game is not a reference. Only decisions where both models answered in time are counted, so a model that often fails looks better
      than it is.
    </section>
  );
}

function Notes({ nodes }: { nodes: NodeStats[] }) {
  const shadows = nodes.flatMap((n) => {
    const s = shadowOf(n);
    return s === undefined ? [] : [s];
  });
  const calls = shadows.reduce((n, b) => n + b.calls, 0);
  const errors = shadows.reduce((n, b) => n + b.errors, 0);
  const rate = calls === 0 ? 0 : errors / calls;
  const slowest = Math.max(0, ...shadows.map((b) => b.error_latency_ms.p50 ?? 0));
  return (
    <section aria-label="Notes" className="text-xs italic">
      <p>
        The shadow answered {calls - errors} of {calls} calls ({errors} errors, {pct(rate)}).{' '}
        {slowest > 0 && `A failed call took about ${Math.round(slowest / 1000)} s (median): a slow failure is usually a timeout.`}
      </p>
      <p>
        If the shadow runs on the same model server as the persona models, its latency includes waiting behind them and being swapped out of memory, so treat it
        as an upper bound, not the model’s own speed. Excluding cold calls does not remove that.
      </p>
    </section>
  );
}

function Disagreements({ nodes, since }: { nodes: NodeStats[]; since: string | undefined }) {
  const [node, setNode] = useState('');
  const [question, setQuestion] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const questions = [...new Set(nodes.filter((n) => node === '' || n.node === node).flatMap((n) => Object.keys(n.question_agreement)))].sort();
  // a question the current node or window no longer has is not a filter any more
  const chosen = questions.includes(question) ? question : '';
  const query = useDisagreements(node, chosen, since);
  return (
    <section aria-label="Disagreements" className="border border-ink bg-card-light p-4">
      <h2 className="text-xl">Where they disagree</h2>
      <div className="mb-2 flex flex-wrap gap-3 text-sm">
        <label>
          Node{' '}
          <select
            value={node}
            onChange={(e) => {
              setNode(e.target.value);
              setQuestion('');
            }}
            className="border border-ink bg-card px-1"
          >
            <option value="">all</option>
            {nodes.map((n) => (
              <option key={n.node} value={n.node}>
                {n.node}
              </option>
            ))}
          </select>
        </label>
        <label>
          Question{' '}
          <select value={chosen} onChange={(e) => setQuestion(e.target.value)} className="border border-ink bg-card px-1">
            <option value="">any</option>
            {questions.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
      </div>
      {query.isPending && <p className="text-sm italic">Loading…</p>}
      {query.isError && (
        <p role="alert" className="text-sm text-stamp">
          {isApiError(query.error) ? query.error.message : 'Could not load the disagreements.'}
        </p>
      )}
      {query.data?.length === 0 && <p className="text-sm italic">No disagreements here.</p>}
      <ul>
        {query.data?.map((d) => {
          const differing = Object.entries(d.agrees)
            .filter(([, ok]) => !ok)
            .map(([q]) => q);
          const expanded = open === d.decision_id;
          return (
            <li key={d.decision_id} className="border-b border-ink/30">
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : d.decision_id)} className="w-full p-1 text-left text-xs">
                <b>{d.node}</b> · differ on {differing.join(', ') || '–'} · {d.state_preview.slice(0, 60)}
              </button>
              {expanded && <DecisionTable decision={d} backends={[]} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Jev against Nimble over every recorded decision. It never depends on the game being on. */
export function StatsPage({ onBack }: { onBack: () => void }) {
  const [date, setDate] = useState('');
  const [includeCold, setIncludeCold] = useState(false);
  const since = sinceToIso(date);
  const stats = useStats(since, includeCold);
  return (
    <main aria-label="Stats" className="mx-auto flex max-w-5xl flex-col gap-4 p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-4xl">Jev vs Nimble</h1>
        <InkButton onClick={onBack}>Back</InkButton>
      </header>
      <Definition />
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label>
          Since <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="border border-ink bg-card px-1" />
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={includeCold} onChange={(e) => setIncludeCold(e.target.checked)} />
          Include cold calls in latency
        </label>
        <InkButton onClick={() => void stats.refetch()}>Refresh</InkButton>
        {stats.data?.since != null && <span className="italic">window starts {stats.data.since}</span>}
      </div>
      {stats.isPending && <p className="italic">Loading the comparison…</p>}
      {stats.isError && (
        <p role="alert" className="text-stamp">
          {isApiError(stats.error) ? stats.error.message : 'Could not load the stats.'}
        </p>
      )}
      {stats.data?.nodes.length === 0 && <p className="italic">No decisions recorded yet. Play with SHADOW_RUN=true to collect a comparison.</p>}
      {stats.data !== undefined && stats.data.nodes.length > 0 && (
        <>
          {stats.data.nodes.map((n) => (
            <NodeCard key={n.node} node={n} />
          ))}
          <Disagreements nodes={stats.data.nodes} since={since} />
          <Notes nodes={stats.data.nodes} />
        </>
      )}
    </main>
  );
}
