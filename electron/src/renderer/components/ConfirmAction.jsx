import React, { useEffect, useState } from "react";
import Button from "./Button.jsx";

function ConfirmAction({
  label,
  confirmLabel,
  tone = "danger",
  onConfirm,
  className = "",
  triggerClassName = "",
  cancelLabel = "Cancel",
}) {
  const [armed, setArmed] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!armed) return undefined;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  async function handleConfirm() {
    if (loading) return;
    setLoading(true);
    try {
      await onConfirm?.();
    } finally {
      setLoading(false);
      setArmed(false);
    }
  }

  if (!armed) {
    const variant = tone === "primary" ? "primary" : tone === "danger" ? "dangerOutline" : "secondary";
    return (
      <span className={["confirm-inline", className].filter(Boolean).join(" ")}>
        <Button variant={variant} className={triggerClassName} onClick={() => setArmed(true)}>
          {label}
        </Button>
      </span>
    );
  }

  return (
    <span className={["confirm-inline-group", className].filter(Boolean).join(" ")}>
      <Button variant="ghost" onClick={() => setArmed(false)}>
        {cancelLabel}
      </Button>
      <Button
        variant={tone === "primary" ? "primary" : "danger"}
        loading={loading}
        onClick={handleConfirm}
      >
        {confirmLabel || `${label} ✓`}
      </Button>
    </span>
  );
}

export default ConfirmAction;
