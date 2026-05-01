import React from "react";
import { clampPercent, usageProgressTone } from "../usage-thresholds.mjs";

function toneFromValue(value) {
  return usageProgressTone(value) || "success";
}

function ProgressBar({ value, className = "", labelClassName = "" }) {
  const resolved = clampPercent(value);
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
