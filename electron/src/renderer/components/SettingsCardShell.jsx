import React from "react";
import SectionCard from "./SectionCard.jsx";

export function SettingsCardShell({
  title,
  description,
  className = "",
  footer = null,
  children,
  testId,
}) {
  return (
    <SectionCard
      className={["control-card", "settings-card", "settings-card-shell", className].filter(Boolean).join(" ")}
      data-testid={testId}
    >
      <div className="settings-card-header">
        <div className="group-title">{title}</div>
        {description ? <p className="muted settings-card-description">{description}</p> : null}
      </div>
      <div className="settings-card-body">{children}</div>
      {footer ? <div className="settings-card-footer">{footer}</div> : null}
    </SectionCard>
  );
}

export function SettingCopy({ label, helper, title = "" }) {
  return (
    <div className="setting-copy">
      <span className="setting-label" title={title}>{label}</span>
      {helper ? <p className="muted setting-copy-helper">{helper}</p> : null}
    </div>
  );
}

export function SettingsSubsection({ title, meta = "", action = null, children }) {
  return (
    <section className="settings-subsection">
      <div className="settings-subsection-head">
        <h3>{title}</h3>
        {(meta || action) ? (
          <div className="settings-subsection-head-side">
            {meta ? <span>{meta}</span> : null}
            {action}
          </div>
        ) : null}
      </div>
      {children}
    </section>
  );
}
