// One toast at a time, bottom right, gone after six seconds (or on Dismiss).

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

type Tone = 'info' | 'error';
interface Toast {
  text: string;
  tone: Tone;
  id: number;
}

const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<number>();
  const say = useCallback((text: string, tone: Tone = 'info') => {
    window.clearTimeout(timer.current);
    setToast({ text, tone, id: Date.now() });
    timer.current = window.setTimeout(() => setToast(null), tone === 'error' ? 9000 : 6000);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <ToastContext.Provider value={say}>
      {children}
      {toast && (
        <div
          key={toast.id}
          role={toast.tone === 'error' ? 'alert' : 'status'}
          className={[
            'fixed right-6 bottom-6 z-20 max-w-[440px] rounded-item px-4 py-3 text-[13px] flex gap-3 items-start text-white',
            'shadow-[0_10px_30px_rgba(20,22,27,.28)]',
            toast.tone === 'error' ? 'bg-bad' : 'bg-ink',
          ].join(' ')}
        >
          <span>{toast.text}</span>
          <button type="button" className="bg-transparent border-0 text-side-text cursor-pointer p-0 text-xs underline" onClick={() => setToast(null)}>
            Dismiss
          </button>
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
