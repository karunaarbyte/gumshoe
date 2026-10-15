import type { NodeStats } from "../api/types";
import { primaryOf, shadowOf } from "./summary";

const ERROR = "(error)";

/** What the game's model chose (rows) against what the shadow chose (columns), per intent. The last
 * column counts the decisions the shadow failed to answer, which no agreement figure includes. */
export function ConfusionMatrix({ node }: { node: NodeStats }) {
  const rows = Object.keys(node.intent_confusion).sort();
  if (rows.length === 0) return null;
  const heard = new Set<string>();
  for (const row of rows)
    for (const col of Object.keys(node.intent_confusion[row]!)) heard.add(col);
  const cols = [
    ...[...heard].filter((c) => c !== ERROR).sort(),
    ...(heard.has(ERROR) ? [ERROR] : []),
  ];
  const primary = primaryOf(node)?.backend ?? "primary";
  const shadow = shadowOf(node)?.backend ?? "shadow";
  return (
    <div className="mb-3 overflow-x-auto">
      <table className="text-xs" data-testid={`matrix-${node.node}`}>
        <caption className="mb-1 text-left text-sm font-bold uppercase">
          Intent: what {primary} chose (rows) against what {shadow} chose
          (columns)
        </caption>
        <thead>
          <tr>
            <th scope="col" className="p-1">
              &nbsp;
            </th>
            {cols.map((c) => (
              <th key={c} scope="col" className="p-1 text-left">
                {c === ERROR ? `${shadow} failed` : c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row}>
              <th scope="row" className="p-1 text-left">
                {row}
              </th>
              {cols.map((col) => {
                const n = node.intent_confusion[row]![col] ?? 0;
                const kind =
                  n === 0
                    ? "empty"
                    : col === ERROR
                      ? "error"
                      : col === row
                        ? "match"
                        : "differ";
                const cls = {
                  empty: "opacity-30",
                  match: "opacity-60",
                  error: "border border-dashed border-ink font-bold",
                  differ: "border border-stamp bg-stamp/20 font-bold",
                }[kind];
                return (
                  <td
                    key={col}
                    data-kind={kind}
                    aria-label={`${primary} chose ${row}, ${shadow} ${col === ERROR ? "failed" : `chose ${col}`}: ${n}`}
                    className={`p-1 text-center tabular-nums ${cls}`}
                  >
                    {n === 0 ? "·" : kind === "differ" ? `≠ ${n}` : n}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
