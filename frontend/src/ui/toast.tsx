import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

export type ToastTone = 'error' | 'notice';
export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastApi {
  show: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
export const TOAST_MS = 6000;

export function ToastProvider({ children, durationMs = TOAST_MS }: { children: ReactNode; durationMs?: number }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback(
    (message: string, tone: ToastTone = 'error') => {
      next.current += 1;
      const id = next.current;
      setToasts((all) => [...all, { id, message, tone }]);
      window.setTimeout(() => dismiss(id), durationMs);
    },
    [dismiss, durationMs],
  );
  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed right-4 bottom-4 z-50 flex w-96 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={`border border-ink p-3 shadow-hard ${t.tone === 'error' ? 'bg-stamp text-card-light' : 'bg-card-light text-ink'}`}
          >
            <span>{t.message}</span>
            <button type="button" className="float-right ml-2 underline" onClick={() => dismiss(t.id)}>
              dismiss
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (api === null) throw new Error('useToast needs a ToastProvider');
  return api;
}
