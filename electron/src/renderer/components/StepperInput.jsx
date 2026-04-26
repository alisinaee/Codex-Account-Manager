import React, { useEffect, useMemo, useState } from "react";

function clampValue(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function StepperInput({
  value,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  step = 1,
  unit = "",
  onChange,
  className = "",
}) {
  const [draft, setDraft] = useState(String(value ?? min));
  const [limitHit, setLimitHit] = useState(false);

  useEffect(() => {
    setDraft(String(value ?? min));
  }, [value, min]);

  useEffect(() => {
    if (!limitHit) return undefined;
    const timer = window.setTimeout(() => setLimitHit(false), 220);
    return () => window.clearTimeout(timer);
  }, [limitHit]);

  const numericDraft = Number(draft);
  const hasNumber = Number.isFinite(numericDraft);
  const isOutOfRange = hasNumber && (numericDraft < min || numericDraft > max);
  const invalid = draft.trim() !== "" && (!hasNumber || isOutOfRange);

  const classes = useMemo(() => [
    "stepper",
    invalid ? "stepper-invalid" : "",
    limitHit ? "stepper-limit-hit" : "",
    className,
  ].filter(Boolean).join(" "), [className, invalid, limitHit]);

  function commit(nextRaw) {
    const parsed = Number(nextRaw);
    if (!Number.isFinite(parsed)) {
      const fallback = clampValue(Number(value) || min, min, max);
      setDraft(String(fallback));
      onChange?.(fallback);
      return;
    }
    const rounded = Math.round(parsed);
    const clamped = clampValue(rounded, min, max);
    if (clamped !== rounded) {
      setLimitHit(true);
    }
    setDraft(String(clamped));
    onChange?.(clamped);
  }

  function handleAdjust(delta) {
    const base = Number.isFinite(Number(value)) ? Number(value) : min;
    commit(base + delta);
  }

  return (
    <div className="inline-stepper-field">
      <div className={classes}>
        <button type="button" onClick={() => handleAdjust(-step)} aria-label="Decrease value">-</button>
        <input
          type="number"
          value={draft}
          min={min}
          max={max}
          step={step}
          aria-invalid={invalid}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => commit(draft)}
        />
        <button type="button" onClick={() => handleAdjust(step)} aria-label="Increase value">+</button>
      </div>
      <span className={`stepper-hint ${invalid ? "visible" : ""}`}>
        Allowed range: {min} to {max}{unit ? ` ${unit}` : ""}
      </span>
    </div>
  );
}

export default StepperInput;
