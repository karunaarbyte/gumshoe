import { type FormEvent, type ReactNode, useState } from 'react';
import { getAdminToken, setAdminToken } from '../api/adminToken';
import { InkButton } from '../ui/Button';

/** Asks for the admin token until one is stored for this tab, then shows its children.
 * The field is uncontrolled, so the token is never mirrored into React state or a DOM attribute. */
export function AdminGate({ children, onBack, notice }: { children: ReactNode; onBack: () => void; notice?: string }) {
  const [has, setHas] = useState(() => getAdminToken() !== null);
  if (has) return <>{children}</>;
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const field = e.currentTarget.elements.namedItem('token') as HTMLInputElement;
    const token = field.value.trim();
    if (token === '') return;
    field.value = '';
    setAdminToken(token);
    setHas(true);
  };
  return (
    <main aria-label="Stats sign-in" className="mx-auto flex max-w-md flex-col gap-4 p-10">
      <h1 className="text-4xl">Stats</h1>
      {notice !== undefined && (
        <p role="alert" className="text-stamp">
          {notice}
        </p>
      )}
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Admin token
          <input name="token" type="password" autoComplete="off" autoCapitalize="off" spellCheck={false} className="border-2 border-ink bg-card-light p-2" />
        </label>
        <div className="flex gap-3">
          <InkButton type="submit">Open the stats</InkButton>
          <InkButton type="button" onClick={onBack}>
            Back
          </InkButton>
        </div>
      </form>
    </main>
  );
}
