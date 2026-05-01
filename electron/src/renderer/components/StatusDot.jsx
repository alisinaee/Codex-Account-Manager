import React from "react";

function StatusDot({ active = false, className = "" }) {
  const label = active ? "Active — currently selected" : "Inactive";
  return (
    <span
      aria-hidden="true"
      title={label}
      className={["status-dot", active ? "active" : "", className].filter(Boolean).join(" ")}
    />
  );
}

export default StatusDot;
