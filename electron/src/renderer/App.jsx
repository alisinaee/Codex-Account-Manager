import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import iconUrl from "../../assets/codex-account-manager.svg";
import "../../../codex_account_manager/web/styles.css";
import "./styles.css";
import {
  AboutIcon,
  AutoRefreshIcon,
  AutoSwitchIcon,
  DebugIcon,
  DoorClosedIcon,
  GuideIcon,
  NotificationsIcon,
  ProfilesIcon,
  SettingsIcon,
  SidebarToggleIcon,
  UpdateIcon,
} from "./icon-pack.jsx";
import {
  buildProfileRowClassName,
  buildSwitchButtonClassName,
  createSwitchController,
  usageTone,
} from "./switch-state.mjs";
import { appendSessionToken, buildAuthenticatedDownloadUrl } from "./request-paths.mjs";
import {
  buildProfileRows,
  buildSidebarCurrentProfile,
  currentProfileName,
  usagePercentNumber,
} from "./view-model.mjs";

function NavIcon({ id }) {
  switch (id) {
    case "profiles":
      return <ProfilesIcon />;
    case "auto-refresh":
      return <AutoRefreshIcon />;
    case "autoswitch":
      return <AutoSwitchIcon />;
    case "notifications":
      return <NotificationsIcon />;
    case "settings":
      return <SettingsIcon />;
    case "guide":
      return <GuideIcon />;
    case "update":
      return <UpdateIcon />;
    case "debug":
      return <DebugIcon />;
    case "about":
      return <AboutIcon />;
    case "exit":
      return <DoorClosedIcon />;
    default:
      return null;
  }
}

const views = [
  { id: "profiles", label: "Profiles", key: "1", icon: "profiles" },
  { id: "auto-refresh", label: "Auto Refresh", key: "2", icon: "auto-refresh" },
  { id: "autoswitch", label: "Auto Switch", key: "3", icon: "autoswitch" },
  { id: "notifications", label: "Notifications", key: "4", icon: "notifications" },
  { id: "settings", label: "Settings", key: ",", icon: "settings" },
  { id: "guide", label: "Guide & Help", key: "?", icon: "guide" },
  { id: "update", label: "Update", key: "u", icon: "update" },
  { id: "debug", label: "Debug", key: "d", icon: "debug" },
  { id: "about", label: "About", key: "a", icon: "about" },
];

const columnDefs = [
  { key: "cur", label: "STS", required: false },
  { key: "profile", label: "Profile", required: false },
  { key: "email", label: "Email", required: false },
  { key: "h5", label: "5H Usage", required: false },
  { key: "h5remain", label: "5H Remain", required: true },
  { key: "h5reset", label: "5H Reset At", required: false },
  { key: "weekly", label: "Weekly", required: false },
  { key: "weeklyremain", label: "W Remain", required: true },
  { key: "weeklyreset", label: "Weekly Reset At", required: false },
  { key: "plan", label: "Plan", required: false },
  { key: "paid", label: "Paid", required: false },
  { key: "id", label: "ID", required: false },
  { key: "added", label: "Added", required: false },
  { key: "note", label: "Note", required: false },
  { key: "auto", label: "Auto", required: false },
  { key: "actions", label: "Actions", required: false },
];

const defaultColumns = {
  cur: true,
  profile: true,
  email: true,
  h5: true,
  h5remain: true,
  h5reset: false,
  weekly: true,
  weeklyremain: true,
  weeklyreset: false,
  plan: false,
  paid: false,
  id: false,
  added: false,
  note: false,
  auto: false,
  actions: true,
};

function normalizeColumns(pref) {
  const next = { ...defaultColumns, ...(pref || {}) };
  next.h5remain = true;
  next.weeklyremain = true;
  return next;
}

function loadStoredColumns() {
  try {
    return normalizeColumns(JSON.parse(localStorage.getItem("codex_table_columns") || "{}"));
  } catch (_) {
    return normalizeColumns(defaultColumns);
  }
}

function saveStoredColumns(prefs) {
  try {
    localStorage.setItem("codex_table_columns", JSON.stringify(normalizeColumns(prefs)));
  } catch (_) {}
}

function isInvalidSessionTokenMessage(error) {
  return /invalid session token/i.test(String(error?.message || error || ""));
}

function usagePercent(row, key) {
  const value = usagePercentNumber(row, key);
  return value === null ? "-" : `${value}%`;
}

function usageValue(row, key) {
  return usagePercentNumber(row, key);
}

function sortRows(rows, sort) {
  const key = sort?.key || "profile";
  const dir = sort?.dir === "asc" ? 1 : -1;
  const current = [];
  const others = [];

  rows.forEach((row) => {
    if (row.is_current) current.push(row);
    else others.push(row);
  });

  const valueFor = (row) => {
    switch (key) {
      case "profile":
        return String(row.name || "").toLowerCase();
      case "email":
        return String(row.email_display || row.email || "").toLowerCase();
      case "cur":
        return row.is_current ? 1 : 0;
      case "h5":
        return usageValue(row, "usage_5h") ?? -1;
      case "weekly":
        return usageValue(row, "usage_weekly") ?? -1;
      case "paid":
        return row.is_paid === true ? 1 : row.is_paid === false ? 0 : -1;
      case "id":
        return String(row.account_id || "").toLowerCase();
      case "added":
        return String(row.saved_at || "").toLowerCase();
      default:
        return String(row.name || "").toLowerCase();
    }
  };

  others.sort((a, b) => {
    const av = valueFor(a);
    const bv = valueFor(b);
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv)) * dir;
    }
    return ((av > bv) - (av < bv)) * dir;
  });

  return [...current, ...others];
}

function fmtReset(ts) {
  if (!ts) return "unknown";
  try {
    const date = new Date(Number(ts) * 1000);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : "unknown";
  } catch (_) {
    return "unknown";
  }
}

function fmtSavedAt(ts) {
  if (!ts) return "-";
  try {
    const date = new Date(ts);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : ts;
  } catch (_) {
    return ts;
  }
}

function fmtRemain(ts, withSeconds = false) {
  if (!ts) return "unknown";
  try {
    let sec = Math.max(0, Math.floor(Number(ts) - (Date.now() / 1000)));
    const d = Math.floor(sec / 86400);
    sec %= 86400;
    const h = Math.floor(sec / 3600);
    sec %= 3600;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (!withSeconds) {
      if (d > 0) return `${d}d ${h}h ${m}m`;
      if (h > 0) return `${h}h ${m}m`;
      return `${m}m`;
    }
    if (d > 0) return `${d}d ${h}h ${m}m ${s}s`;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    return `${m}m ${s}s`;
  } catch (_) {
    return "unknown";
  }
}

function fmtPaid(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "-";
}

function updateNumber(value, delta, min = 0, max = Number.MAX_SAFE_INTEGER, fallback = min) {
  const base = Number.isFinite(Number(value)) ? Number(value) : fallback;
  return Math.max(min, Math.min(max, base + delta));
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.onload = () => {
      const text = String(reader.result || "");
      const base64 = text.includes(",") ? text.split(",")[1] : text;
      resolve(base64);
    };
    reader.readAsDataURL(file);
  });
}

function ModalShell({ title, children, footer, onClose, wide = false }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <div className={`modal-card ${wide ? "wide" : ""}`} onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

function UsageCell({ row, usageKey }) {
  const value = usageValue(row, usageKey);
  const tone = usageTone(value);
  const width = value === null ? 0 : Math.max(0, Math.min(100, value));

  return (
    <div className={`usage-cell ${value === null ? "usage-cell-loading" : ""}`}>
      <span className={`usage-pct ${tone ? `usage-${tone}` : "loading-text"}`}>{value === null ? "-" : `${value}%`}</span>
      <span className={`usage-meter ${value === null ? "loading" : ""}`}>
        <span className={`usage-fill ${tone}`} style={{ width: `${width}%` }} />
      </span>
    </div>
  );
}

function UsageStrip({ label, value, compact = false }) {
  const tone = usageTone(value);
  const width = value === null ? 0 : Math.max(0, Math.min(100, value));

  if (compact) {
    return (
      <div className="sidebar-usage-compact">
        <span className="sidebar-usage-label">{label}</span>
        <span className={tone ? `usage-${tone}` : "loading-text"}>{value === null ? "-" : `${value}%`}</span>
      </div>
    );
  }

  return (
    <div className="sidebar-usage-row">
      <div className="sidebar-usage-head">
        <span className="sidebar-usage-label">{label}</span>
        <span className={tone ? `usage-${tone}` : "loading-text"}>{value === null ? "-" : `${value}%`}</span>
      </div>
      <div className={`usage-meter sidebar-usage-meter ${value === null ? "loading" : ""}`}>
        <span className={`usage-fill ${tone}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function SidebarCurrentProfile({ state, mode }) {
  const summary = buildSidebarCurrentProfile(state);

  return (
    <section className={`sidebar-current ${mode === "minimal" ? "minimal" : ""}`} data-testid="sidebar-current-profile">
      {mode === "fixed" ? (
        <>
          <strong className="sidebar-current-name" title={summary.name || "No active profile"}>{summary.name || "No active profile"}</strong>
          <span className="sidebar-current-email" title={summary.email}>{summary.email}</span>
          <UsageStrip label="5H" value={summary.usage5h} />
          <UsageStrip label="Weekly" value={summary.usageWeekly} />
        </>
      ) : (
        <>
          <strong className="sidebar-current-name" title={summary.name || "No active profile"}>{summary.name || "No active profile"}</strong>
          <UsageStrip label="5H" value={summary.usage5h} compact />
          <UsageStrip label="W" value={summary.usageWeekly} compact />
        </>
      )}
    </section>
  );
}

function Sidebar({ state, activeView, mode, onModeChange, onNavigate, updateAvailable, onExit }) {
  function expandFromMinimal() {
    if (mode === "minimal") {
      onModeChange("fixed");
    }
  }

  return (
    <aside className={`sidebar ${mode}`} data-testid="desktop-sidebar" onClick={expandFromMinimal}>
      <div className="sidebar-top">
        <div className="brand" onClick={(event) => event.stopPropagation()}>
          <img src={iconUrl} alt="" />
          {mode === "fixed" && (
            <div>
              <strong>Codex Account</strong>
              <span>Desktop</span>
            </div>
          )}
        </div>
        <button
          className="sidebar-icon-toggle"
          onClick={(event) => {
            event.stopPropagation();
            onModeChange(mode === "fixed" ? "minimal" : "fixed");
          }}
          title={mode === "fixed" ? "Collapse sidebar" : "Expand sidebar"}
          aria-label={mode === "fixed" ? "Collapse sidebar" : "Expand sidebar"}
        >
          <SidebarToggleIcon />
        </button>
      </div>

      <nav aria-label="Desktop sections" onClick={(event) => event.stopPropagation()}>
        {views.map((view) => (
          <button
            key={view.id}
            className={activeView === view.id ? "active" : ""}
            onClick={() => onNavigate(view.id)}
            title={view.label}
            aria-label={view.label}
          >
            <span className="nav-mark"><NavIcon id={view.icon} /></span>
            {mode === "fixed" && <span>{view.label}</span>}
            {view.id === "update" && updateAvailable && <span className="nav-dot" aria-hidden="true" />}
          </button>
        ))}
      </nav>

      <div
        className={`sidebar-expand-hitarea ${mode === "minimal" ? "active" : ""}`}
        data-testid="sidebar-expand-hitarea"
        aria-hidden="true"
      />

      <div onClick={(event) => event.stopPropagation()}>
        <SidebarCurrentProfile state={state} mode={mode} />
      </div>

      <button
        className={`sidebar-exit-btn ${mode === "minimal" ? "minimal" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onExit?.();
        }}
        title="Exit"
        aria-label="Exit"
      >
        <span className="nav-mark"><NavIcon id="exit" /></span>
        {mode === "fixed" && <span>Exit</span>}
      </button>
    </aside>
  );
}

function TopBar({ activeTitle, updateStatus, loading, onRefresh, onRestart }) {
  return (
    <header className="topbar desktop-topbar">
      <div className="topbar-meta">
        <span className="topbar-section-title">{activeTitle}</span>
        {updateStatus?.update_available && <span className="badge badge-warn">Update {updateStatus.latest_version || "available"}</span>}
      </div>
      <div className="top-actions">
        <button className="btn btn-warning topbar-compact-btn" onClick={onRestart}>Restart</button>
        <button className={loading ? "btn btn-primary btn-progress topbar-compact-btn" : "btn btn-primary topbar-compact-btn"} onClick={onRefresh} disabled={loading}>{loading ? "Refreshing" : "Refresh"}</button>
      </div>
    </header>
  );
}

function AccountsTable({ profiles, switching, activatedProfile, visibleColumns, sort, onSort, onSwitch, onOpenRowActions, onToggleEligibility, wideMode }) {
  const column = (key, className, children) => (visibleColumns[key] ? <td data-col={key} className={className}>{children}</td> : null);

  return (
    <table className={wideMode ? "wide-columns" : ""}>
      <thead>
        <tr>
          {columnDefs.map((col) => (visibleColumns[col.key] ? (
            <th key={col.key} data-col={col.key} onClick={() => onSort(col.key)} className={`sortable ${sort.key === col.key ? "sorted" : ""}`}>
              {col.label}
              <span className="sort-indicator">{sort.key === col.key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
            </th>
          ) : null))}
        </tr>
      </thead>
      <tbody>
        {profiles.map((profile) => {
          const quotaBlocked = (usageValue(profile, "usage_5h") ?? 1) <= 0 || (usageValue(profile, "usage_weekly") ?? 1) <= 0;
          const disableSwitch = profile.is_current || Boolean(switching);
          const rowClass = buildProfileRowClassName({
            isCurrent: profile.is_current,
            isPending: switching === profile.name,
            isActivated: activatedProfile === profile.name,
          });

          return (
            <tr key={profile.name} className={rowClass}>
              {column("cur", null, <span className={profile.is_current ? "status-dot active" : "status-dot"} aria-hidden="true" />)}
              {column("profile", null, <strong className="profile-name">{profile.name}</strong>)}
              {column("email", "email-cell", <span className="muted" title={profile.email_display}>{profile.email_display}</span>)}
              {column("h5", null, <UsageCell row={profile} usageKey="usage_5h" />)}
              {column("h5remain", "reset-cell", <span className="muted">{fmtRemain(profile.usage_5h?.resets_at, true)}</span>)}
              {column("h5reset", "reset-cell", <span className="muted">{fmtReset(profile.usage_5h?.resets_at)}</span>)}
              {column("weekly", null, <UsageCell row={profile} usageKey="usage_weekly" />)}
              {column("weeklyremain", "reset-cell", <span className="muted">{fmtRemain(profile.usage_weekly?.resets_at)}</span>)}
              {column("weeklyreset", "reset-cell", <span className="muted">{fmtReset(profile.usage_weekly?.resets_at)}</span>)}
              {column("plan", null, <span className="muted">{profile.plan_type || "-"}</span>)}
              {column("paid", null, <span className="muted">{fmtPaid(profile.is_paid)}</span>)}
              {column("id", "id-cell", <span className="muted" title={profile.account_id || "-"}>{profile.account_id || "-"}</span>)}
              {column("added", "added-cell", <span className="muted">{fmtSavedAt(profile.saved_at)}</span>)}
              {column("note", "note-cell", profile.same_principal ? <span className="badge">same-principal</span> : null)}
              {column("auto", null, <label className="toggle"><input type="checkbox" checked={!!profile.auto_switch_eligible} onChange={(event) => onToggleEligibility(profile.name, event.target.checked)} /></label>)}
              {column("actions", null, (
                <div className="actions-cell">
                  <button className={`${quotaBlocked ? "btn btn-primary-danger" : buildSwitchButtonClassName(switching === profile.name)} ${disableSwitch ? "btn-disabled" : ""}`} disabled={disableSwitch} onClick={() => onSwitch(profile.name)}>
                    {switching === profile.name ? "Switching" : "Switch"}
                  </button>
                  <button className="btn actions-menu-btn" data-row-actions={profile.name} aria-label={`row actions ${profile.name}`} title="Row actions" onClick={() => onOpenRowActions(profile.name)}>⋯</button>
                </div>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function AccountsMobileList({ profiles, switching, onSwitch, onOpenRowActions }) {
  return (
    <div className="mobile-list" data-testid="profiles-mobile-list">
      {profiles.map((profile) => {
        const h5Value = usageValue(profile, "usage_5h");
        const weeklyValue = usageValue(profile, "usage_weekly");
        const quotaBlocked = (h5Value ?? 1) <= 0 || (weeklyValue ?? 1) <= 0;
        const switchDisabled = profile.is_current || Boolean(switching);
        const h5Tone = usageTone(h5Value);
        const weeklyTone = usageTone(weeklyValue);

        return (
          <div key={profile.name} className="mobile-row">
            <div className="mobile-head">
              <div className="mobile-left">
                <span className={profile.is_current ? "status-dot active" : "status-dot"} aria-hidden="true" />
                <span className="mobile-profile">{profile.name || "-"}</span>
              </div>
              <div className="mobile-actions">
                <button className={`${quotaBlocked ? "btn btn-primary-danger" : "btn btn-primary"} ${switchDisabled ? "btn-disabled" : ""} ${switching === profile.name ? "btn-progress" : ""}`} disabled={switchDisabled} onClick={() => onSwitch(profile.name)}>
                  {switching === profile.name ? "Switching" : "Switch"}
                </button>
                <button className="btn actions-menu-btn" data-mobile-row-actions={profile.name} onClick={() => onOpenRowActions(profile.name)}>⋯</button>
              </div>
            </div>
            <div className="mobile-email">{profile.email_display}</div>
            <div className="mobile-stats">
              <div className="mobile-stat"><span className="label">5H</span><span className={h5Tone ? `usage-${h5Tone}` : "loading-text"}>{usagePercent(profile, "usage_5h")}</span></div>
              <div className="mobile-stat"><span className="label">Weekly</span><span className={weeklyTone ? `usage-${weeklyTone}` : "loading-text"}>{usagePercent(profile, "usage_weekly")}</span></div>
              <div className="mobile-stat"><span className="label">5H Remain</span><span>{fmtRemain(profile.usage_5h?.resets_at, true)}</span></div>
              <div className="mobile-stat"><span className="label">W Remain</span><span>{fmtRemain(profile.usage_weekly?.resets_at)}</span></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProfilesView({ state, switching, activatedProfile, onSwitch, onAddAccount, onImportProfiles, onExportProfiles, onRemoveAll, onOpenColumns, onOpenRowActions, onToggleEligibility, visibleColumns, sort, onSort }) {
  const profiles = sortRows(buildProfileRows(state), sort);
  const visibleColumnCount = Object.values(visibleColumns || {}).filter(Boolean).length;
  const wideMode = visibleColumnCount > 8;

  return (
    <section className="view profiles-view" data-testid="profiles-view">
      <div className="profiles-view-shell">
        <div className="accounts-toolbar">
          <div className="spacer" />
          <div className="accounts-actions">
            <button className="btn btn-primary" onClick={onAddAccount}>Add Account</button>
            <button className="btn" onClick={onImportProfiles}>Import</button>
            <button className="btn" onClick={onExportProfiles}>Export</button>
            <button className="btn btn-primary-danger" onClick={onRemoveAll}>Remove All</button>
            <button className="btn" onClick={onOpenColumns}>Columns</button>
          </div>
        </div>
        <div className={`table-wrap profiles-table-wrap ${wideMode ? "wide-columns" : ""}`}>
          <AccountsTable
            profiles={profiles}
            switching={switching}
            activatedProfile={activatedProfile}
            visibleColumns={visibleColumns}
            wideMode={wideMode}
            sort={sort}
            onSort={onSort}
            onSwitch={onSwitch}
            onOpenRowActions={onOpenRowActions}
            onToggleEligibility={onToggleEligibility}
          />
          <AccountsMobileList
            profiles={profiles}
            switching={switching}
            onSwitch={onSwitch}
            onOpenRowActions={onOpenRowActions}
          />
        </div>
      </div>
    </section>
  );
}

function InlineStepper({ value, min, max, step = 1, unit, onChange }) {
  return (
    <div className="stepper compact">
      <button type="button" onClick={() => onChange(updateNumber(value, -step, min, max, min))}>-</button>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value || min))} />
      <button type="button" onClick={() => onChange(updateNumber(value, step, min, max, min))}>+</button>
      {unit ? <span className="label">{unit}</span> : null}
    </div>
  );
}

function AutoRefreshView({ state, loading, onRefresh, onSavePatch }) {
  const ui = state?.config?.ui || {};

  return (
    <section className="view" data-testid="auto-refresh-view">
      <div className="controls-grid auto-refresh-grid">
        <section className="control-card settings-card">
          <div className="group-title">Current Account Auto Refresh</div>
          <div className="setting-row inset-row refresh-setting-row">
            <span className="setting-label">Current Account Auto Refresh</span>
            <div className="field-block refresh-setting-controls">
              <InlineStepper
                value={ui.current_refresh_interval_sec ?? 5}
                min={1}
                max={3600}
                unit="sec"
                onChange={(value) => onSavePatch({ ui: { current_refresh_interval_sec: value } })}
              />
              <label className="toggle refresh-setting-toggle"><input type="checkbox" checked={!!ui.current_auto_refresh_enabled} onChange={(event) => onSavePatch({ ui: { current_auto_refresh_enabled: event.target.checked } })} /></label>
            </div>
          </div>
        </section>
        <section className="control-card settings-card">
          <div className="group-title">Auto Refresh All</div>
          <div className="setting-row inset-row refresh-setting-row">
            <span className="setting-label">Auto Refresh All</span>
            <div className="field-block refresh-setting-controls">
              <InlineStepper
                value={ui.all_refresh_interval_min ?? 5}
                min={1}
                max={60}
                unit="min"
                onChange={(value) => onSavePatch({ ui: { all_refresh_interval_min: value } })}
              />
              <label className="toggle refresh-setting-toggle"><input type="checkbox" checked={!!ui.all_auto_refresh_enabled} onChange={(event) => onSavePatch({ ui: { all_auto_refresh_enabled: event.target.checked } })} /></label>
            </div>
          </div>
        </section>
      </div>
      <div className="settings-inline-actions auto-refresh-actions">
        <button className={loading ? "btn btn-primary btn-progress" : "btn btn-primary"} onClick={onRefresh} disabled={loading}>{loading ? "Refreshing" : "Refresh"}</button>
      </div>
    </section>
  );
}

function useCountdownText(dueAtText, dueAt) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!dueAt) {
    return dueAtText || "Switch in 00:00";
  }

  const remaining = Math.max(0, Math.floor(Number(dueAt) - now / 1000));
  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  return `Switch in ${mm}:${ss}`;
}

function AutoSwitchView({ state, onSavePatch, onOpenChainEdit, onRunSwitch, onRapidTest, onStopTests, onTestAutoSwitch, onAutoArrange }) {
  const autoState = state?.autoSwitch || {};
  const autoConfig = state?.config?.auto_switch || {};
  const countdownText = useCountdownText(autoState.pending_switch_due_at_text, autoState.pending_switch_due_at);
  const chainOrder = Array.isArray(state?.list?.profiles) ? state.list.profiles.map((row) => row.name) : [];
  const chainRows = sortRows(buildProfileRows(state), { key: "profile", dir: "asc" }).filter((row) => chainOrder.includes(row.name));

  return (
    <section className="view" data-testid="autoswitch-view">
      <section className={`card auto-switch-card ${autoState.pending_switch_due_at ? "armed" : ""}`} style={{ padding: 12 }}>
        <div className="auto-switch-head">
          <div className="k" style={{ marginBottom: 0 }}>Auto-Switch Rules</div>
          <div className={`auto-switch-countdown ${autoState.pending_switch_due_at ? "active" : ""}`}>{countdownText}</div>
        </div>
        <div className="rules-grid">
          <div className="rules-col settings-card">
            <div className="rules-title">Execution</div>
            <div className="setting-row">
              <span className="setting-label">Enabled</span>
              <label className="toggle"><input type="checkbox" checked={!!autoConfig.enabled} onChange={(event) => onSavePatch({ auto_switch: { enabled: event.target.checked } })} /></label>
            </div>
            <div className="setting-row metric inset-row">
              <span className="setting-label">Delay (sec)</span>
              <InlineStepper
                value={autoConfig.delay_sec ?? 60}
                min={0}
                max={3600}
                onChange={(value) => onSavePatch({ auto_switch: { delay_sec: value } })}
              />
            </div>
            <div className="status-row">
              <div>
                <div className="k">Switch in flight</div>
                <div className="v">{autoState.switch_in_flight ? autoState.switch_target || "Running" : "No"}</div>
              </div>
              <div>
                <div className="k">Pending switch</div>
                <div className="v">{countdownText}</div>
              </div>
            </div>
            <div className="exec-actions">
              <button className="btn btn-primary" onClick={onRunSwitch}>Run Switch</button>
              <button className="btn" onClick={onRapidTest}>Rapid Test</button>
              <button className="btn btn-danger" onClick={onStopTests}>Stop Tests</button>
              <button className="btn" onClick={onTestAutoSwitch}>Test Auto Switch</button>
            </div>
          </div>
          <div className="rules-col settings-card">
            <div className="rules-title">Selection Policy</div>
            <div className="setting-field">
              <span className="setting-label">Ranking</span>
              <select value={autoConfig.ranking_mode || "balanced"} onChange={(event) => onSavePatch({ auto_switch: { ranking_mode: event.target.value } })}>
                <option value="balanced">balanced</option>
                <option value="max_5h">max_5h</option>
                <option value="max_weekly">max_weekly</option>
                <option value="manual">manual</option>
              </select>
            </div>
            <div className="metric-pair-grid">
              <div className="setting-row metric inset-row">
                <span className="setting-label">5H switch %</span>
                <InlineStepper
                  value={autoConfig.thresholds?.h5_switch_pct ?? 20}
                  min={0}
                  max={100}
                  onChange={(value) => onSavePatch({ auto_switch: { thresholds: { h5_switch_pct: value } } })}
                />
              </div>
              <div className="setting-row metric inset-row">
                <span className="setting-label">Weekly switch %</span>
                <InlineStepper
                  value={autoConfig.thresholds?.weekly_switch_pct ?? 20}
                  min={0}
                  max={100}
                  onChange={(value) => onSavePatch({ auto_switch: { thresholds: { weekly_switch_pct: value } } })}
                />
              </div>
            </div>
            <div className="field-row rules-actions">
              <button className="btn btn-primary" onClick={onAutoArrange}>Auto Arrange</button>
            </div>
          </div>
        </div>
        <div className="chain-panel">
          <div className="chain-head">
            <div className="chain-title">Switch Chain Preview</div>
            <button className="btn" onClick={onOpenChainEdit}>Edit</button>
          </div>
          <div className="chain-track">
            {chainRows.length ? chainRows.map((row) => (
              <span key={row.name} className="chain-node">
                <span className="chain-name">{row.name}</span>
                <span className={`chain-metric usage-${usageTone(usageValue(row, "usage_5h"))}`}>5H {usagePercent(row, "usage_5h")}</span>
                <span className={`chain-metric usage-${usageTone(usageValue(row, "usage_weekly"))}`}>W {usagePercent(row, "usage_weekly")}</span>
              </span>
            )) : <span className="muted">No profiles available.</span>}
          </div>
        </div>
      </section>
    </section>
  );
}

function NotificationsView({ state, onNotify, onSavePatch }) {
  const notifications = state?.config?.notifications || {};

  return (
    <section className="view" data-testid="notifications-view">
      <div className="controls-grid">
        <section className="control-card notify-card settings-card">
          <div className="group-title">Notification</div>
          <div className="setting-row inset-row">
            <span className="setting-label">Enable notifications</span>
            <label className="toggle"><input type="checkbox" checked={!!notifications.enabled} onChange={(event) => onSavePatch({ notifications: { enabled: event.target.checked } })} /></label>
          </div>
          <div className="metric-pair-grid">
            <div className="setting-row metric inset-row">
              <span className="setting-label">5H notify %</span>
              <InlineStepper
                value={notifications.thresholds?.h5_warn_pct ?? 20}
                min={0}
                max={100}
                onChange={(value) => onSavePatch({ notifications: { thresholds: { h5_warn_pct: value } } })}
              />
            </div>
            <div className="setting-row metric inset-row">
              <span className="setting-label">Weekly notify %</span>
              <InlineStepper
                value={notifications.thresholds?.weekly_warn_pct ?? 20}
                min={0}
                max={100}
                onChange={(value) => onSavePatch({ notifications: { thresholds: { weekly_warn_pct: value } } })}
              />
            </div>
          </div>
          <div className="alarm-actions">
            <button className="btn btn-warning btn-block" type="button" onClick={onNotify}>Test Notification</button>
          </div>
        </section>
      </div>
    </section>
  );
}

function SettingsView({ state, onRestart, onKillAll, onToggleTheme, onToggleDebug }) {
  const ui = state?.config?.ui || {};

  return (
    <section className="view" data-testid="settings-view">
      <div className="controls-grid">
        <section className="control-card settings-card">
          <div className="group-title">Appearance</div>
          <div className="setting-row inset-row">
            <span className="setting-label">Theme mode</span>
            <strong>{ui.theme || "auto"}</strong>
          </div>
          <div className="settings-inline-actions">
            <button className="btn" onClick={onToggleTheme}>Cycle Theme</button>
            <button className="btn" onClick={onToggleDebug}>Toggle Logs</button>
          </div>
        </section>
        <section className="control-card settings-card">
          <div className="group-title">Maintenance</div>
          <p className="muted">Keep the desktop shell aligned with the web panel while still exposing app-level controls here.</p>
          <div className="settings-inline-actions">
            <button className="btn btn-warning" onClick={onRestart}>Restart</button>
            <button className="btn btn-primary-danger" onClick={onKillAll}>Kill All</button>
          </div>
        </section>
      </div>
    </section>
  );
}

function GuideView({ releaseNotes, onRefreshReleaseNotes }) {
  const notes = Array.isArray(releaseNotes?.releases) ? releaseNotes.releases : [];

  return (
    <section className="view">
      <div className="settings-panel">
        <div><label>Quick Start</label><strong>Use Add Account, Switch, Import, Export, and Auto Switch from the desktop shell.</strong></div>
        <div><label>Desktop parity</label><strong>Electron mirrors the web panel behavior, dialogs, and table controls.</strong></div>
        <div><label>Release notes</label><strong>{notes[0]?.tag || "No release notes loaded"}</strong></div>
        <div className="settings-inline-actions">
          <button className="btn" onClick={onRefreshReleaseNotes}>Refresh</button>
        </div>
        <div className="guide-notes">
          {notes.slice(0, 3).map((note) => (
            <article key={note.tag} className="metric-card">
              <span>{note.tag}</span>
              <strong>{note.title || note.tag}</strong>
              <small>{Array.isArray(note.highlights) ? note.highlights.join(" • ") : String(note.body || "").slice(0, 140)}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function UpdateView({ updateStatus, onCheck, onRunUpdate }) {
  return (
    <section className="view">
      <div className="settings-panel">
        <div><label>Current version</label><strong>{updateStatus?.current_version || "-"}</strong></div>
        <div><label>Latest version</label><strong>{updateStatus?.latest_version || "-"}</strong></div>
        <div><label>Status</label><strong>{updateStatus?.status_text || updateStatus?.status || "unknown"}</strong></div>
        <div className="settings-inline-actions">
          <button className="btn" onClick={onCheck}>Check for Updates</button>
          <button className="btn btn-primary" onClick={onRunUpdate} disabled={!updateStatus?.update_available}>Update Now</button>
        </div>
      </div>
    </section>
  );
}

function DebugView({ debugLogs, onExport }) {
  return (
    <section className="view">
      <div className="settings-inline-actions">
        <button className="btn" onClick={onExport}>Export Debug Logs</button>
      </div>
      <div className="debug-log-panel">
        {debugLogs?.length ? debugLogs.slice(-120).map((row, index) => (
          <div key={`${row.ts || index}-${index}`} className={`debug-line log-${String(row.level || "info")}`}>
            <span>{row.ts || "-"}</span>
            <strong>{String(row.level || "info").toUpperCase()}</strong>
            <span>{row.message || ""}</span>
          </div>
        )) : <div className="muted">No logs yet.</div>}
      </div>
    </section>
  );
}

function AboutView({ backendState }) {
  return (
    <section className="view">
      <div className="settings-panel">
        <div><label>Desktop shell</label><strong>Electron renderer with Python backend</strong></div>
        <div><label>Stable web panel</label><strong>Still available through codex-account ui</strong></div>
        <div><label>Backend</label><strong>{backendState?.baseUrl || "127.0.0.1:4673"}</strong></div>
      </div>
    </section>
  );
}

function App() {
  const desktop = window.codexAccountDesktop;
  const [activeView, setActiveView] = useState("profiles");
  const [sidebarMode, setSidebarMode] = useState(window.innerWidth < 1100 ? "minimal" : "fixed");
  const [state, setState] = useState(null);
  const [backendState, setBackendState] = useState(null);
  const [releaseNotes, setReleaseNotes] = useState(null);
  const [updateStatus, setUpdateStatus] = useState(null);
  const [debugLogs, setDebugLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState("");
  const [activatedProfile, setActivatedProfile] = useState("");
  const [error, setError] = useState("");
  const [columnPrefs, setColumnPrefs] = useState(loadStoredColumns());
  const [sort, setSort] = useState({ key: "profile", dir: "asc" });
  const [modal, setModal] = useState(null);
  const switchControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const exportSelectionRef = useRef([]);
  const [chainOrder, setChainOrder] = useState([]);

  const activeTitle = useMemo(() => views.find((view) => view.id === activeView)?.label || "Profiles", [activeView]);
  const updateAvailable = !!updateStatus?.update_available;
  const visibleColumns = useMemo(() => normalizeColumns(columnPrefs), [columnPrefs]);

  async function request(path, options = {}) {
    try {
      return await desktop.request(path, options);
    } catch (error) {
      if (!isInvalidSessionTokenMessage(error)) {
        throw error;
      }
      await desktop.refresh().catch(() => null);
      return desktop.request(path, options);
    }
  }

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      const [core, backend] = await Promise.all([
        desktop.getState(),
        desktop.getBackendState(),
      ]);
      const [update, notes, logs, chain] = await Promise.all([
        request("/api/app-update-status", {}),
        request("/api/release-notes", {}),
        request(appendSessionToken("/api/debug/logs?tail=240", backend?.token), {}),
        request("/api/auto-switch/chain", {}),
      ]);
      setState(core);
      setBackendState(backend);
      setUpdateStatus(update);
      setReleaseNotes(notes);
      setDebugLogs(Array.isArray(logs?.logs) ? logs.logs : Array.isArray(logs) ? logs : []);
      setChainOrder(Array.isArray(chain?.chain) ? chain.chain : []);
      if (core?.config?.ui?.column_prefs) {
        setColumnPrefs(normalizeColumns(core.config.ui.column_prefs));
      }
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  async function refreshState() {
    await loadAll();
  }

  async function saveUiPatch(patch) {
    const next = await desktop.saveConfig(patch);
    setState(next);
    if (patch?.ui?.column_prefs) {
      setColumnPrefs(normalizeColumns(patch.ui.column_prefs));
      saveStoredColumns(patch.ui.column_prefs);
    }
    return next;
  }

  async function switchProfile(name) {
    const target = String(name || "").trim();
    if (!target || switching) return;
    if (!switchControllerRef.current) {
      switchControllerRef.current = createSwitchController((profileName) => desktop.switchProfile(profileName));
    }
    setSwitching(target);
    setActivatedProfile("");
    setError("");
    try {
      const next = await switchControllerRef.current.switchProfile(target);
      setState(next);
      setActivatedProfile(target);
      setTimeout(() => setActivatedProfile((current) => (current === target ? "" : current)), 1100);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setSwitching("");
    }
  }

  async function testNotification() {
    setError("");
    try {
      await desktop.testNotification();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function restartUiService() {
    try {
      await request("/api/system/restart", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function killAll() {
    try {
      await request("/api/system/kill-all", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function toggleTheme() {
    const current = state?.config?.ui?.theme || "auto";
    const next = current === "auto" ? "dark" : current === "dark" ? "light" : "auto";
    await saveUiPatch({ ui: { theme: next } });
  }

  async function toggleDebug() {
    const current = !!state?.config?.ui?.debug_mode;
    await saveUiPatch({ ui: { debug_mode: !current } });
  }

  async function checkForUpdates() {
    try {
      const next = await request("/api/app-update-status?force=true", {});
      setUpdateStatus(next);
      setActiveView("update");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function runUpdate() {
    try {
      const next = await request("/api/system/update", { method: "POST", body: JSON.stringify({}) });
      setUpdateStatus(next.update_status || updateStatus);
      await loadAll();
      setActiveView("update");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function onExportDebug() {
    try {
      const payload = {
        exported_at: new Date().toISOString(),
        state,
        backendState,
        releaseNotes,
        updateStatus,
        logs: debugLogs,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `codex-account-debug-${Date.now()}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1200);
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function openColumnsModal() {
    setModal({ type: "columns" });
  }

  async function openRowActions(name) {
    setModal({ type: "row-actions", name });
  }

  async function openAddAccount() {
    setModal({ type: "add-account", name: "", mode: "device", session: null });
  }

  async function openExportProfiles() {
    exportSelectionRef.current = buildProfileRows(state).map((row) => row.name);
    setModal({ type: "export", filename: "profiles", selected: exportSelectionRef.current });
  }

  async function openImportProfiles() {
    setModal({ type: "import", file: null, analysis: null });
  }

  async function openChainEditor() {
    setModal({ type: "chain-edit", chain: Array.isArray(chainOrder) ? [...chainOrder] : [] });
  }

  async function openUpdateView() {
    setActiveView("update");
  }

  async function toggleEligibility(name, eligible) {
    try {
      await request("/api/auto-switch/account-eligibility", {
        method: "POST",
        body: JSON.stringify({ name, eligible }),
      });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function runRapidTest() {
    try {
      await request("/api/auto-switch/rapid-test", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function runAutoSwitch() {
    try {
      await request("/api/auto-switch/run-switch", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function stopTests() {
    try {
      await request("/api/auto-switch/stop-tests", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function testAutoSwitch() {
    try {
      await request("/api/auto-switch/test", { method: "POST", body: JSON.stringify({ timeout_sec: 30 }) });
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function autoArrange() {
    try {
      const next = await request("/api/auto-switch/auto-arrange", { method: "POST", body: JSON.stringify({}) });
      setChainOrder(Array.isArray(next?.chain) ? next.chain : []);
      await loadAll();
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function startAddAccount(mode, name) {
    const target = String(name || "").trim();
    if (!target) return;
    const payload = mode === "device"
      ? await request("/api/local/add/start", { method: "POST", body: JSON.stringify({ name: target, timeout: 600, device_auth: true }) })
      : await request("/api/local/add", { method: "POST", body: JSON.stringify({ name: target, timeout: 600, device_auth: false }) });
    if (mode === "device") {
      setModal((current) => ({ ...current, session: payload }));
    } else {
      await loadAll();
      setModal(null);
    }
  }

  async function importAnalyze(file) {
    if (!file) return;
    const content_b64 = await fileToBase64(file);
    const payload = await request("/api/local/import/analyze", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content_b64 }),
    });
    setModal({ type: "import-review", file, analysis: payload, selections: payload?.profiles || [] });
  }

  async function applyImport(analysis, selections) {
    await request("/api/local/import/apply", {
      method: "POST",
      body: JSON.stringify({ analysis_id: analysis?.analysis_id, profiles: selections }),
    });
    setModal(null);
    await loadAll();
  }

  async function handleRename(name) {
    const newName = window.prompt("Rename profile", name || "");
    if (!newName || !newName.trim() || newName.trim() === name) return;
    await request("/api/local/rename", {
      method: "POST",
      body: JSON.stringify({ old_name: name, new_name: newName.trim() }),
    });
    await loadAll();
  }

  async function handleRemove(name) {
    if (!window.confirm(`Remove profile '${name}'?`)) return;
    await request("/api/local/remove", { method: "POST", body: JSON.stringify({ name }) });
    await loadAll();
  }

  async function handleRemoveAll() {
    if (!window.confirm("Remove ALL saved profiles?")) return;
    await request("/api/local/remove-all", { method: "POST", body: JSON.stringify({}) });
    await loadAll();
  }

  async function handleExportProfiles(names, filename) {
    const payload = await request("/api/local/export/prepare", {
      method: "POST",
      body: JSON.stringify({ scope: "selected", names, filename }),
    });
    if (backendState?.baseUrl && backendState?.token) {
      const href = buildAuthenticatedDownloadUrl(
        backendState.baseUrl,
        "/api/local/export/download",
        backendState.token,
        { id: payload.export_id },
      );
      const res = await fetch(href, { method: "GET", cache: "no-store", credentials: "same-origin" });
      if (!res.ok) throw new Error(`download failed (${res.status})`);
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = payload.filename || `${filename || "profiles"}.camzip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    }
    setModal(null);
    await loadAll();
  }

  async function loadReleaseNotes(force = false) {
    const notes = await request(force ? "/api/release-notes?force=true" : "/api/release-notes", {});
    setReleaseNotes(notes);
  }

  async function loadDebugLogs() {
    const logs = await request(appendSessionToken("/api/debug/logs?tail=240", backendState?.token), {});
    setDebugLogs(Array.isArray(logs?.logs) ? logs.logs : Array.isArray(logs) ? logs : []);
  }

  useEffect(() => {
    loadAll();
    const offNavigate = desktop.onNavigate((view) => setActiveView(view === "usage" ? "profiles" : view));
    const offSidebar = desktop.onToggleSidebar(() => setSidebarMode((mode) => (mode === "fixed" ? "minimal" : "fixed")));
    return () => {
      offNavigate?.();
      offSidebar?.();
    };
  }, []);

  useEffect(() => {
    if (activeView === "guide") loadReleaseNotes().catch(() => {});
    if (activeView === "debug") loadDebugLogs().catch(() => {});
    if (activeView === "update") loadAll().catch(() => {});
  }, [activeView]);

  return (
    <main className="desktop-shell" data-testid="electron-renderer">
      <Sidebar
        state={state}
        activeView={activeView}
        mode={sidebarMode}
        onModeChange={setSidebarMode}
        onNavigate={setActiveView}
        updateAvailable={updateAvailable}
        onExit={killAll}
      />
      <div className="workspace">
        <TopBar
          activeTitle={activeTitle}
          updateStatus={updateStatus}
          loading={loading}
          onRefresh={refreshState}
          onRestart={restartUiService}
        />
        {activeView === "profiles" && (
          <ProfilesView
            state={state}
            switching={switching}
            activatedProfile={activatedProfile}
            onSwitch={switchProfile}
            onAddAccount={openAddAccount}
            onImportProfiles={openImportProfiles}
            onExportProfiles={openExportProfiles}
            onRemoveAll={handleRemoveAll}
            onOpenColumns={openColumnsModal}
            onOpenRowActions={openRowActions}
            onToggleEligibility={toggleEligibility}
            visibleColumns={visibleColumns}
            sort={sort}
            onSort={(key) => setSort((current) => ({ key, dir: current.key === key && current.dir === "asc" ? "desc" : "asc" }))}
          />
        )}
        {activeView === "auto-refresh" && (
          <AutoRefreshView
            state={state}
            loading={loading}
            onRefresh={refreshState}
            onSavePatch={saveUiPatch}
          />
        )}
        {activeView === "autoswitch" && (
          <AutoSwitchView
            state={state}
            onSavePatch={saveUiPatch}
            onOpenChainEdit={openChainEditor}
            onRunSwitch={runAutoSwitch}
            onRapidTest={runRapidTest}
            onStopTests={stopTests}
            onTestAutoSwitch={testAutoSwitch}
            onAutoArrange={autoArrange}
          />
        )}
        {activeView === "notifications" && <NotificationsView state={state} onNotify={testNotification} onSavePatch={saveUiPatch} />}
        {activeView === "settings" && <SettingsView state={state} onRestart={restartUiService} onKillAll={killAll} onToggleTheme={toggleTheme} onToggleDebug={toggleDebug} />}
        {activeView === "guide" && <GuideView releaseNotes={releaseNotes} onRefreshReleaseNotes={() => loadReleaseNotes(true).catch(() => {})} />}
        {activeView === "update" && <UpdateView updateStatus={updateStatus} onCheck={checkForUpdates} onRunUpdate={runUpdate} />}
        {activeView === "debug" && <DebugView debugLogs={debugLogs} onExport={onExportDebug} />}
        {activeView === "about" && <AboutView backendState={backendState} />}
        {error ? <div className="workspace-error" role="alert">{error}</div> : null}
      </div>

      {modal?.type === "columns" && (
        <ModalShell title="Table Columns" onClose={() => setModal(null)} footer={<><button className="btn" onClick={() => { setColumnPrefs(defaultColumns); saveStoredColumns(defaultColumns); setModal(null); }}>Reset Defaults</button><button className="btn btn-primary" onClick={() => setModal(null)}>Done</button></>}>
          <div className="columns-grid">
            {columnDefs.filter((col) => !col.required).map((col) => (
              <label key={col.key} className="modal-check">
                <input
                  type="checkbox"
                  checked={!!visibleColumns[col.key]}
                  onChange={(event) => {
                    const next = normalizeColumns({ ...visibleColumns, [col.key]: event.target.checked });
                    setColumnPrefs(next);
                    saveStoredColumns(next);
                    saveUiPatch({ ui: { column_prefs: next } }).catch(() => {});
                  }}
                />
                <span>{col.label}</span>
              </label>
            ))}
          </div>
        </ModalShell>
      )}

      {modal?.type === "row-actions" && (
        <ModalShell title="Row Actions" onClose={() => setModal(null)} footer={<button className="btn" onClick={() => setModal(null)}>Done</button>}>
          <p>Profile: {modal.name}</p>
          <div className="settings-inline-actions">
            <button className="btn" onClick={() => { setModal(null); handleRename(modal.name).catch((e) => setError(e?.message || String(e))); }}>Rename</button>
            <button className="btn btn-danger" onClick={() => { setModal(null); handleRemove(modal.name).catch((e) => setError(e?.message || String(e))); }}>Remove</button>
          </div>
        </ModalShell>
      )}

      {modal?.type === "add-account" && (
        <ModalShell title="Add Account" onClose={() => setModal(null)} footer={<button className="btn" onClick={() => setModal(null)}>Close</button>}>
          <div className="modal-form">
            <label>Profile name</label>
            <input value={modal.name} onChange={(event) => setModal((current) => ({ ...current, name: event.target.value }))} placeholder="work" />
            <label>Login mode</label>
            <select value={modal.mode} onChange={(event) => setModal((current) => ({ ...current, mode: event.target.value }))}>
              <option value="device">Device Login</option>
              <option value="normal">Normal Login</option>
            </select>
            <div className="settings-inline-actions">
              <button className="btn btn-primary" onClick={() => startAddAccount(modal.mode, modal.name).catch((e) => setError(e?.message || String(e)))}>Start</button>
            </div>
            {modal.session && (
              <div className="modal-card-inline">
                <div><label>Status</label><strong>{modal.session.status || "-"}</strong></div>
                <div><label>URL</label><strong>{modal.session.url || "-"}</strong></div>
                <div><label>Code</label><strong>{modal.session.code || "-"}</strong></div>
              </div>
            )}
          </div>
        </ModalShell>
      )}

      {modal?.type === "export" && (
        <ModalShell title="Export Profiles" onClose={() => setModal(null)} footer={<button className="btn btn-primary" onClick={() => handleExportProfiles(modal.selected || [], modal.filename || "profiles").catch((e) => setError(e?.message || String(e)))}>Export Selected</button>}>
          <div className="modal-form">
            <label>Archive name</label>
            <input value={modal.filename} onChange={(event) => setModal((current) => ({ ...current, filename: event.target.value }))} />
            <div className="columns-grid">
              {buildProfileRows(state).map((row) => (
                <label key={row.name} className="modal-check">
                  <input
                    type="checkbox"
                    checked={(modal.selected || []).includes(row.name)}
                    onChange={(event) => setModal((current) => {
                      const next = new Set(current.selected || []);
                      if (event.target.checked) next.add(row.name);
                      else next.delete(row.name);
                      return { ...current, selected: Array.from(next) };
                    })}
                  />
                  <span>{row.name}</span>
                </label>
              ))}
            </div>
          </div>
        </ModalShell>
      )}

      {modal?.type === "import" && (
        <ModalShell title="Import Profiles" onClose={() => setModal(null)} footer={<><input ref={fileInputRef} type="file" accept=".camzip,application/zip" style={{ display: "none" }} onChange={(event) => { const file = event.target.files?.[0]; if (file) importAnalyze(file).catch((err) => setError(err?.message || String(err))); event.target.value = ""; }} /><button className="btn" onClick={() => fileInputRef.current?.click()}>Choose Archive</button></>}>
          <p>Imported data may grant account access. Keep exported files private.</p>
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()}>Analyze Import</button>
        </ModalShell>
      )}

      {modal?.type === "import-review" && (
        <ModalShell title="Import Review" wide onClose={() => setModal(null)} footer={<button className="btn btn-primary" onClick={() => applyImport(modal.analysis, modal.selections || []).catch((e) => setError(e?.message || String(e)))}>Apply Import</button>}>
          <p>Archive: {modal.file?.name || "uploaded file"}</p>
          <div className="columns-grid">
            {(modal.analysis?.profiles || []).map((row) => (
              <label key={row.name} className="modal-check">
                <input
                  type="checkbox"
                  checked={(modal.selections || []).some((item) => item.name === row.name)}
                  onChange={(event) => setModal((current) => {
                    const next = [...(current.selections || [])];
                    if (event.target.checked) next.push(row);
                    else next.splice(next.findIndex((item) => item.name === row.name), 1);
                    return { ...current, selections: next };
                  })}
                />
                <span>{row.name}</span>
              </label>
            ))}
          </div>
        </ModalShell>
      )}

      {modal?.type === "chain-edit" && (
        <ModalShell title="Edit Switch Chain" wide onClose={() => setModal(null)} footer={<button className="btn btn-primary" onClick={() => { request("/api/auto-switch/chain", { method: "POST", body: JSON.stringify({ chain: modal.chain || [] }) }).then(() => loadAll()).catch((e) => setError(e?.message || String(e))); setModal(null); }}>Save</button>}>
          <p>Drag order is simplified to up/down controls in the desktop shell.</p>
          <div className="chain-list">
            {(modal.chain || []).map((name, index) => (
              <div key={name} className="chain-row">
                <strong>{name}</strong>
                <div className="settings-inline-actions">
                  <button className="btn" disabled={index === 0} onClick={() => setModal((current) => {
                    const next = [...current.chain];
                    [next[index - 1], next[index]] = [next[index], next[index - 1]];
                    return { ...current, chain: next };
                  })}>Up</button>
                  <button className="btn" disabled={index === (modal.chain || []).length - 1} onClick={() => setModal((current) => {
                    const next = [...current.chain];
                    [next[index + 1], next[index]] = [next[index], next[index + 1]];
                    return { ...current, chain: next };
                  })}>Down</button>
                </div>
              </div>
            ))}
          </div>
        </ModalShell>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
