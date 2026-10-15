import type { GameState } from "../api/types";
import { Chip, StampButton } from "../ui/Button";

interface Props {
  state: GameState;
  canAccuse: boolean;
  onAccuse: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
}

/** The left rail: facts by source (with speaker), the record kinds, the contradictions found,
 * and the Accuse button. */
export function Notebook({
  state,
  canAccuse,
  onAccuse,
  collapsed = false,
  onToggle,
}: Props) {
  const { notebook, brief } = state;
  const toggle = (label: string, glyph: string) =>
    onToggle !== undefined && (
      <button
        type="button"
        aria-label={label}
        aria-expanded={!collapsed}
        title={label}
        onClick={onToggle}
        className="border border-ink bg-card-light px-2 py-1 font-bold"
      >
        {glyph}
      </button>
    );
  if (collapsed) {
    return (
      <nav
        aria-label="Notebook"
        className="flex h-full min-h-0 flex-col items-center gap-3 border-r border-ink bg-card p-2"
      >
        {toggle("Open the notebook", "»")}
        <p className="text-center text-xs leading-tight">
          Attempts left
          <b className="block text-base text-stamp">{brief.attempts_left}</b>
        </p>
        <StampButton
          className="mt-auto w-full px-1 text-[11px] tracking-wider"
          disabled={!canAccuse}
          onClick={onAccuse}
        >
          Accuse
        </StampButton>
      </nav>
    );
  }
  return (
    <nav
      aria-label="Notebook"
      className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto border-r border-ink bg-card p-3"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xl">Notebook</h2>
        {toggle("Hide the notebook", "«")}
      </div>
      <p className="text-center text-xs">
        Attempts left: {brief.attempts_left}
      </p>
      {notebook.sections.length === 0 && (
        <p className="text-sm italic">Nothing noted yet.</p>
      )}
      {notebook.sections.map((s) => (
        <section key={s.source} aria-label={s.source}>
          <h3 className="text-sm font-bold uppercase">{s.source}</h3>
          <ul className="list-disc pl-4 text-sm">
            {s.facts.map((f) => (
              <li key={f.handle} className={f.contradicted ? "text-stamp" : ""}>
                {f.speaker !== null && <b>{f.speaker}: </b>}
                {f.text}
                {f.contradicted && (
                  <span className="ml-1 text-[10px] uppercase">
                    contradicted
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <section aria-label="Records">
        <Chip>Records</Chip>
        <ul className="pl-1 text-sm">
          {brief.record_kinds.map((r) => (
            <li key={r.key}>{r.label}</li>
          ))}
        </ul>
      </section>
      {notebook.contradictions.length > 0 && (
        <section aria-label="Contradictions">
          <Chip>Contradictions</Chip>
          <ul className="pl-1 text-sm text-stamp">
            {notebook.contradictions.map((c) => (
              <li key={`${c.lie}~${c.exposer}`}>{c.text}</li>
            ))}
          </ul>
        </section>
      )}
      <StampButton className="mt-auto" disabled={!canAccuse} onClick={onAccuse}>
        Accuse
      </StampButton>
    </nav>
  );
}
