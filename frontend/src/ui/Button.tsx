import type { ComponentPropsWithRef, ReactNode } from 'react';

type Props = ComponentPropsWithRef<'button'> & { children: ReactNode };

const base = 'px-4 py-2 font-display uppercase tracking-[0.2em] text-sm disabled:opacity-40 disabled:cursor-not-allowed';

/** The red stamp block: the main action (ACCUSE, NEW CASE, YES). */
export function StampButton({ className = '', type = 'button', ...props }: Props) {
  return <button type={type} className={`${base} bg-stamp text-card-light shadow-hard ${className}`} {...props} />;
}

/** The outlined ink button: everything secondary. */
export function InkButton({ className = '', type = 'button', ...props }: Props) {
  return <button type={type} className={`${base} border border-ink bg-card text-ink ${className}`} {...props} />;
}

/** A small-caps label in an inverted ink chip ("SUSPECT"). */
export function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-block bg-ink px-1.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-card-light">{children}</span>;
}
