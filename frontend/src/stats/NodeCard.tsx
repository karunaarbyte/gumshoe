import type { BackendStats, NodeStats } from "../api/types";
import { ms } from "../trace/compare";
import {
  agreementText,
  comparedLine,
  costLabel,
  offsetText,
  pct,
  primaryOf,
  shadowOf,
  timeoutRate,
  wilson,
} from "./summary";

function Row({
  label,
  cells,
  note,
}: {
  label: string;
  cells: (string | number)[];
  note?: string;
}) {
  return (
    <tr>
      <th scope="row" className="p-1 text-left font-normal">
        {label}
        {note !== undefined && (
          <span className="block text-[10px] italic">{note}</span>
        )}
      </th>
      {cells.map((c, i) => (
        <td key={i} className="p-1 tabular-nums">
          {c}
        </td>
      ))}
    </tr>
  );
}

function AgreementBar({
  question,
  rate,
  n,
  offset,
}: {
  question: string;
  rate: number;
  n: number;
  offset: number | undefined;
}) {
  const [lo, hi] = wilson(Math.round(rate * n), n);
  return (
    <li className="mb-2">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-bold">{question}</span>
        <span className="tabular-nums">
          {agreementText(rate, n)} · 95% range {pct(lo)}–{pct(hi)}
        </span>
      </div>
      <div className="h-2 w-full bg-ink/15" aria-hidden="true">
        <div
          className="h-2 bg-ink"
          style={{ width: `${Math.round(rate * 100)}%` }}
        />
      </div>
      {offset !== undefined && (
        <p className="text-[10px] italic">
          average difference: {offsetText(offset)}
        </p>
      )}
    </li>
  );
}

/** One node of the comparison. Leads with how much of the node the comparison really covers. */
export function NodeCard({ node }: { node: NodeStats }) {
  const primary = primaryOf(node);
  const shadow = shadowOf(node);
  const cols: BackendStats[] = [primary, shadow].filter(
    (b): b is BackendStats => b !== undefined,
  );
  const questions = Object.keys(node.question_agreement);
  return (
    <section
      aria-label={`Node ${node.node}`}
      className="border border-ink bg-card-light p-4"
    >
      <h2 className="text-xl">{node.node}</h2>
      <p className="mb-3 text-sm" data-testid={`compared-${node.node}`}>
        {comparedLine(node)}
      </p>
      {shadow === undefined && (
        <p className="mb-3 text-sm italic">
          No shadow ran on this node: nothing to compare.
        </p>
      )}

      <table className="mb-3 w-full text-xs">
        <caption className="sr-only">
          {node.node}: the two backends side by side
        </caption>
        <thead>
          <tr>
            <th scope="col" className="p-1 text-left">
              &nbsp;
            </th>
            {cols.map((b) => (
              <th key={b.backend} scope="col" className="p-1 text-left">
                {b.backend}{" "}
                <span className="font-normal">
                  ({b.role === "primary" ? "decides" : "shadow"})
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <Row label="calls" cells={cols.map((b) => b.calls)} />
          <Row
            label="errors"
            cells={cols.map((b) => `${b.errors} (${pct(timeoutRate(b))})`)}
            note="about 30 s each: likely timeouts"
          />
          <Row
            label="latency p50"
            cells={cols.map((b) => ms(b.latency_ms.p50))}
            note="answered calls only"
          />
          <Row
            label="latency p95"
            cells={cols.map((b) => ms(b.latency_ms.p95))}
            note="answered calls only"
          />
          {cols.some((b) => b.errors > 0) && (
            <Row
              label="failed calls p50"
              cells={cols.map((b) => ms(b.error_latency_ms.p50))}
            />
          )}
          <Row label="cost" cells={cols.map(costLabel)} />
        </tbody>
      </table>

      <details className="mb-3 text-xs">
        <summary>
          Per backend, not comparable between models (tokens, confidence)
        </summary>
        <p className="italic">
          Each model counts tokens and scales confidence differently: compare a
          backend only to itself over time.
        </p>
        <table className="w-full">
          <tbody>
            <Row
              label="mean tokens in / out"
              cells={cols.map(
                (b) =>
                  `${b.mean_input_tokens ?? "–"} / ${b.mean_output_tokens ?? "–"}`,
              )}
            />
            <Row
              label="mean confidence"
              cells={cols.map((b) =>
                b.mean_confidence === null ? "–" : b.mean_confidence.toFixed(2),
              )}
            />
          </tbody>
        </table>
      </details>

      {questions.length > 0 && (
        <>
          <h3 className="mb-1 text-sm font-bold uppercase">
            Agreement by question (decisions both answered in time)
          </h3>
          <ul className="mb-3">
            {questions.map((q) => (
              <AgreementBar
                key={q}
                question={q}
                rate={node.question_agreement[q]!}
                n={node.compared}
                offset={node.score_offset[q]}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
