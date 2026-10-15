import type { CallView, DecisionView } from "../api/types";
import { isApiError } from "../api/errors";
import { useDecision } from "../data/queries";
import { ms, questionsOf, usd } from "./compare";

/** The calls in column order: the health's primary, then its shadow (when there is one). */
function columns(
  decision: DecisionView,
  backends: string[],
): (CallView | undefined)[] {
  return backends.map((b) => decision.calls.find((c) => c.backend === b));
}

function CallFooter({ call }: { call: CallView | undefined }) {
  if (call === undefined)
    return <td className="p-1 text-xs italic">not asked</td>;
  return (
    <td className="p-1 align-top text-xs">
      <div>
        {ms(call.latency_ms)} · {call.input_tokens ?? "–"}/
        {call.output_tokens ?? "–"} tok · {usd(call.est_cost_usd)}
      </div>
      <div className="flex gap-1">
        {call.used && <span className="bg-ink px-1 text-card-light">used</span>}
        {call.cold && <span className="border border-ink px-1">cold</span>}
      </div>
      {call.error !== null && (
        <div className="text-stamp">error: {call.error}</div>
      )}
    </td>
  );
}

/** A decision's side-by-side table. Pure: it highlights the questions the server says disagree. */
export function DecisionTable({
  decision: d,
  backends,
}: {
  decision: DecisionView;
  backends: string[];
}) {
  // health names the columns; without it, the backends the decision itself lists
  const names =
    backends.length > 0
      ? backends
      : [...new Set(d.calls.map((c) => c.backend))];
  const cols = columns(d, names);
  return (
    <div
      className="my-2 border border-ink bg-card-light p-2"
      data-testid={`decision-${d.decision_id}`}
    >
      <p className="text-xs">
        <b>{d.node}</b>{" "}
        {d.fallback && (
          <span className="bg-stamp px-1 text-card-light">fallback</span>
        )}
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="text-left">question</th>
            {names.map((b) => (
              <th key={b} className="text-left">
                {b}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {questionsOf(d).map((q) => {
            // the server's own rule (a score within a band is not a disagreement), not a string compare
            const differ = d.agrees[q] === false;
            return (
              <tr
                key={q}
                data-disagree={differ}
                className={differ ? "bg-stamp/20 font-bold" : ""}
              >
                <td className="p-1">{q}</td>
                {cols.map((c, i) => {
                  const a = c?.answers[q];
                  return (
                    <td key={names[i]} className="p-1">
                      {a === undefined
                        ? "–"
                        : `${a.verdict} (${a.confidence.toFixed(2)})`}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          <tr>
            <td className="p-1 text-xs">calls</td>
            {cols.map((c, i) => (
              <CallFooter key={names[i]} call={c} />
            ))}
          </tr>
        </tbody>
      </table>
      <details className="text-xs">
        <summary>state preview</summary>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words">
          {d.state_preview}
        </pre>
      </details>
    </div>
  );
}

export function DecisionPanel({
  id,
  backends,
  retryBaseMs,
}: {
  id: string;
  backends: string[];
  retryBaseMs?: number;
}) {
  const query = useDecision(id, retryBaseMs);
  if (query.isPending)
    return <p className="text-xs italic">Fetching decision {id}…</p>;
  if (query.isError) {
    const text = isApiError(query.error, "not_recorded_yet")
      ? "not recorded yet"
      : isApiError(query.error)
        ? query.error.message
        : "could not be loaded";
    return (
      <p className="text-xs text-stamp">
        Decision {id}: {text}
      </p>
    );
  }
  return <DecisionTable decision={query.data} backends={backends} />;
}
