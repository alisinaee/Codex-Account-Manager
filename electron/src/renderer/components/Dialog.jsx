import React, { useEffect, useId } from "react";
import { DialogCloseIcon } from "../icon-pack.jsx";

function Dialog({ title, children, footer, onClose, size = "md" }) {
  const titleId = useId();

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  function onBackdropMouseDown(event) {
    if (event.target === event.currentTarget) {
      onClose?.();
    }
  }

  return (
    <div className="dialog-backdrop" onMouseDown={onBackdropMouseDown}>
      <section
        className={`dialog-panel dialog-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="dialog-header">
          <h3 id={titleId} className="dialog-title">{title}</h3>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="Close dialog">
            <DialogCloseIcon />
          </button>
        </header>
        <div className="dialog-content">{children}</div>
        {footer ? <footer className="dialog-actions">{footer}</footer> : null}
      </section>
    </div>
  );
}

export default Dialog;
