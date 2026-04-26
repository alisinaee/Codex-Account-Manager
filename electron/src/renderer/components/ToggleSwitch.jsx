import React from "react";

function ToggleSwitch({ checked = false, onChange, ariaLabel, disabled = false, title = "" }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      className={`toggle-switch ${checked ? "is-on" : ""}`}
      onClick={() => {
        if (!disabled) {
          onChange?.(!checked);
        }
      }}
      disabled={disabled}
      title={title}
    >
      <span className="toggle-thumb" aria-hidden="true" />
    </button>
  );
}

export default ToggleSwitch;
