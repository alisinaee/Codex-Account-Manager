import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

const ToastContext = createContext({
  showToast: () => {},
});

function normalizeToast(input = {}) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    tone: input.tone || "success",
    title: input.title || "Done",
    description: input.description || "",
  };
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const removeToast = useCallback((id) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const showToast = useCallback((input) => {
    const toast = normalizeToast(input);
    setToasts((current) => [...current, toast]);
    window.setTimeout(() => removeToast(toast.id), 3000);
    return toast.id;
  }, [removeToast]);

  const contextValue = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <article key={toast.id} className={`toast ${toast.tone}`}>
            <strong className="toast-title">{toast.title}</strong>
            {toast.description ? <p className="toast-description">{toast.description}</p> : null}
          </article>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
