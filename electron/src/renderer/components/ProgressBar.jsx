import React from "react";

function toneFromValue(value) {
  if (!Number.isFinite(value)) return "success";
  if (value >= 90) return "danger";
  if (value >= 70) return "warning";
  return "success";
}

function ProgressBar({ value, className = "", labelClassName = "" }) {
  const numeric = Number(value);
  const resolved = Number.isFinite(numeric) ? Math.max(0, Math.min(100, Math.round(numeric))) : null;
  const tone = toneFromValue(resolved);
  const label = resolved === null ? "-" : `${resolved}%`;
  const widthClass = resolved === null ? "progress-width-0" : `progress-width-${resolved}`;

  return (
    <div className={["progress-line", className].filter(Boolean).join(" ")}>
      <span className={["progress-label", labelClassName, `progress-tone-${tone}`].filter(Boolean).join(" ")}>{label}</span>
      <span className="progress-bar" aria-hidden="true">
        <span className={["progress-fill", `progress-tone-${tone}`, widthClass].join(" ")} />
      </span>
    </div>
  );
}

export default ProgressBar;
