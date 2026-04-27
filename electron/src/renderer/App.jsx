import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import iconUrl from "../../assets/codex-account-manager.svg";
import "./styles.css";
import {
  AboutIcon,
  AutoSwitchIcon,
  DebugIcon,
  DoorClosedIcon,
  GuideIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  ProfilesIcon,
  SettingsIcon,
  UpdateIcon,
} from "./icon-pack.jsx";
import {
  buildProfileRowClassName,
  createSwitchController,
} from "./switch-state.mjs";
import { appendSessionToken, buildAuthenticatedDownloadUrl } from "./request-paths.mjs";
import {
  buildProfileRows,
  buildSidebarCurrentProfile,
  usagePercentNumber,
} from "./view-model.mjs";
import {
  arcDasharray,
  clampPercent,
  formatFullDateFromSeconds,
  formatFullDateFromValue,
  formatShortDateFromSeconds,
  formatShortDateFromValue,
  remainToneFromResetEpochSeconds,
  truncateAccountId,
  truncateNote,
  usageColor,
} from "./table-layout.mjs";
import {
  applyProfileSelection,
  deepMerge,
  formatAutoSwitchCountdown,
  getAllRefreshIntervalMs,
  getCurrentRefreshIntervalMs,
  waitForServiceRestart,
} from "./parity.mjs";
import Badge from "./components/Badge.jsx";
import Button from "./components/Button.jsx";
import ConfirmAction from "./components/ConfirmAction.jsx";
import DataTable from "./components/DataTable.jsx";
import Dialog from "./components/Dialog.jsx";
import SectionCard from "./components/SectionCard.jsx";
import StatusDot from "./components/StatusDot.jsx";
import StepperInput from "./components/StepperInput.jsx";
import { ToastProvider, useToast } from "./components/ToastProvider.jsx";
import ToggleSwitch from "./components/ToggleSwitch.jsx";

function NavIcon({ id }) {
  switch (id) {
    case "profiles":
      return <ProfilesIcon />;
    case "autoswitch":
      return <AutoSwitchIcon />;
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
  { id: "autoswitch", label: "Auto Switch", key: "2", icon: "autoswitch" },
  { id: "settings", label: "Settings", key: ",", icon: "settings" },
  { id: "guide", label: "Guide & Help", key: "?", icon: "guide" },
  { id: "update", label: "Update", key: "u", icon: "update" },
  { id: "debug", label: "Debug", key: "d", icon: "debug" },
  { id: "about", label: "About", key: "a", icon: "about" },
];

function normalizeViewId(view) {
  switch (view) {
    case "usage":
      return "profiles";
    case "auto-refresh":
    case "notifications":
      return "settings";
    default:
      return view;
  }
}

const columnDefs = [
  { key: "cur", label: "Status", required: false },
  { key: "profile", label: "Profile", required: false },
  { key: "email", label: "Email", required: false },
  { key: "h5", label: "5h usage", required: false },
  { key: "h5remain", label: "5h remain", required: true },
  { key: "h5reset", label: "5h reset at", required: false },
  { key: "weekly", label: "Weekly", required: false },
  { key: "weeklyremain", label: "W remain", required: true },
  { key: "weeklyreset", label: "Weekly reset at", required: false },
  { key: "plan", label: "Plan", required: false },
  { key: "paid", label: "Paid", required: false },
  { key: "id", label: "Id", required: false },
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
  h5reset: true,
  weekly: true,
  weeklyremain: true,
  weeklyreset: true,
  plan: true,
  paid: true,
  id: true,
  added: true,
  note: true,
  auto: true,
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
  const value = usageValue(row, key);
  return value === null ? "-" : `${value}%`;
}

function usageValue(row, key) {
  return clampPercent(usagePercentNumber(row, key));
}

function usageTone(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  if (numeric >= 90) return "danger";
  if (numeric >= 70) return "warning";
  return "success";
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
  return formatShortDateFromSeconds(ts);
}

function fmtResetFull(ts) {
  return formatFullDateFromSeconds(ts);
}

function fmtSavedAt(ts) {
  return formatShortDateFromValue(ts);
}

function fmtSavedAtFull(ts) {
  return formatFullDateFromValue(ts);
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

function remainToneClass(ts) {
  const tone = remainToneFromResetEpochSeconds(ts);
  if (tone === "danger") return "remain-danger";
  if (tone === "warning") return "remain-warning";
  return "remain-normal";
}

const tableColumnLayout = {
  cur: { colClassName: "col-status", width: "24px" },
  profile: { colClassName: "col-profile", width: "7%" },
  email: { colClassName: "col-email", width: "12%" },
  h5: { colClassName: "col-5h", width: "7%" },
  h5remain: { colClassName: "col-5h-rem", width: "6%" },
  h5reset: { colClassName: "col-5h-reset", width: "7%" },
  weekly: { colClassName: "col-weekly", width: "7%" },
  weeklyremain: { colClassName: "col-w-rem", width: "6%" },
  weeklyreset: { colClassName: "col-w-reset", width: "7%" },
  plan: { colClassName: "col-plan", width: "4%" },
  paid: { colClassName: "col-paid", width: "4%" },
  id: { colClassName: "col-id", width: "6%" },
  added: { colClassName: "col-added", width: "5%" },
  note: { colClassName: "col-note", width: "4%" },
  auto: { colClassName: "col-auto", width: "48px" },
  actions: { colClassName: "col-actions", width: "116px" },
};

function planBadgeVariant(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "neutral";
  if (normalized.includes("team")) return "warning";
  if (normalized.includes("plus") || normalized.includes("pro")) return "success";
  return "neutral";
}

function isColumnVisibleForViewport(key, viewportSizeClass) {
  if (viewportSizeClass === "size-compact") {
    return !["h5remain", "weeklyremain", "h5reset", "weeklyreset", "plan", "paid", "id", "added", "note", "auto"].includes(key);
  }
  if (viewportSizeClass === "size-normal") {
    return !["id", "added", "note", "h5reset", "weeklyreset"].includes(key);
  }
  if (viewportSizeClass === "size-wide") {
    return !["id", "note"].includes(key);
  }
  return true;
}

function tableUsageColor(value) {
  const percent = clampPercent(value);
  if (percent === null) return "var(--text-secondary)";
  if (percent <= 10) return "var(--color-red)";
  if (percent <= 30) return "var(--color-amber)";
  return "var(--color-green)";
}

const WIDTH_CLASS_NAMES = ["size-compact", "size-normal", "size-wide", "size-ultrawide"];
const HEIGHT_CLASS_NAMES = ["height-short", "height-normal", "height-tall"];

function classifyWidth(width) {
  const numeric = Number(width);
  if (numeric < 1000) return "size-compact";
  if (numeric < 1300) return "size-normal";
  if (numeric < 1700) return "size-wide";
  return "size-ultrawide";
}

function classifyHeight(height) {
  const numeric = Number(height);
  if (numeric < 640) return "height-short";
  if (numeric <= 900) return "height-normal";
  return "height-tall";
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

function isRuntimeOperational(status) {
  if (status?.phase === "ready") {
    return true;
  }
  return Boolean(
    status?.python?.supported
      && status?.core?.installed
      && status?.uiService?.running,
  );
}

function waitMs(delay) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, delay);
  });
}

function joinBaseUrl(baseUrl, path) {
  return `${String(baseUrl || "").replace(/\/+$/, "")}${String(path || "")}`;
}

function LabelValueRow({ label, value }) {
  return (
    <div className="kv-row">
      <span className="kv-label">{label}</span>
      <div className="kv-value">{value}</div>
    </div>
  );
}

function formatReleaseDate(value) {
  if (!value) return "";
  try {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value);
    return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch (_) {
    return String(value);
  }
}

function formatLogLevel(level) {
  const normalized = String(level || "info").toLowerCase();
  if (normalized === "warn" || normalized === "warning") return "Warn";
  if (normalized === "error") return "Error";
  return "Info";
}

function UsageCell({ row, usageKey }) {
  const value = usageValue(row, usageKey);
  const color = tableUsageColor(value);
  const label = value === null ? "-" : `${value}%`;

  return (
    <div className={`usage-cell ${value === null ? "usage-cell-loading" : ""}`} title={value === null ? "Usage unavailable" : `${value}% remaining`}>
      <div className="usage-top">
        <span className={`usage-pct ${value === null ? "loading-text" : ""}`} style={value === null ? undefined : { color }}>
          {label}
        </span>
      </div>
      <div className="usage-bar-track" aria-hidden="true">
        <div
          className="usage-bar-fill"
          style={value === null ? { width: "0%" } : { width: `${value}%`, background: color }}
        />
      </div>
    </div>
  );
}

function UsageStrip({ label, value, compact = false }) {
  const labelValue = value === null ? "-" : `${value}%`;
  const color = usageColor(value);

  if (compact) {
    return (
      <div className="sidebar-usage-compact">
        <span className="sidebar-usage-label" title={label === "5h" ? "5h means the five-hour usage window." : undefined}>{label}</span>
        <span className={value === null ? "loading-text" : "sidebar-usage-pct"} style={value === null ? undefined : { color }}>
          {labelValue}
        </span>
      </div>
    );
  }

  return (
    <div className="sidebar-usage-row">
      <div className="sidebar-usage-head">
        <span className="sidebar-usage-label" title={label === "5h" ? "5h means the five-hour usage window." : undefined}>{label}</span>
        <span className={value === null ? "loading-text" : "sidebar-usage-pct"} style={value === null ? undefined : { color }}>
          {labelValue}
        </span>
      </div>
      <div className="sidebar-usage-track" aria-hidden="true">
        <div
          className="sidebar-usage-fill"
          style={value === null ? { width: "0%" } : { width: `${value}%`, background: color }}
        />
      </div>
    </div>
  );
}

function SidebarUsageArc({ metric, value }) {
  const label = value === null ? "-" : `${value}%`;
  const color = usageColor(value);
  const arcLabel = metric.toLowerCase() === "weekly" ? "W" : "5h";

  return (
    <svg
      className={`sidebar-usage-arc arc-${metric.toLowerCase()}`}
      viewBox="0 0 36 36"
      role="img"
      aria-label={`${metric}: ${label} used`}
      title={`${metric}: ${label} used`}
    >
      <circle cx="18" cy="18" r="15" fill="none" stroke="var(--border-default)" strokeWidth="3" />
      <g transform="rotate(-90 18 18)">
        <circle
          cx="18"
          cy="18"
          r="15"
          fill="none"
          stroke={value === null ? "var(--text-disabled)" : color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={arcDasharray(value)}
        />
      </g>
      <text
        x="18"
        y="19"
        textAnchor="middle"
        dominantBaseline="middle"
        className={value === null ? "sidebar-usage-arc-label loading-text" : "sidebar-usage-arc-label"}
      >
        {arcLabel}
      </text>
    </svg>
  );
}

function SidebarCurrentProfile({ state, mode }) {
  const summary = buildSidebarCurrentProfile(state);

  return (
    <section className={`sidebar-current ${mode === "minimal" ? "minimal" : ""}`} data-testid="sidebar-current-profile" onClick={(event) => event.stopPropagation()}>
      {mode === "fixed" ? (
        <>
          <strong className="sidebar-current-name" title={summary.name || "No active profile"}>{summary.name || "No active profile"}</strong>
          <span className="sidebar-current-email" title={summary.email}>{summary.email}</span>
          <UsageStrip label="5h" value={summary.usage5h} />
          <UsageStrip label="Weekly" value={summary.usageWeekly} />
        </>
      ) : (
        <div className="sidebar-account-mini">
          <SidebarUsageArc metric="5h" value={summary.usage5h} />
          <SidebarUsageArc metric="Weekly" value={summary.usageWeekly} />
        </div>
      )}
    </section>
  );
}

function Sidebar({ state, activeView, mode, canToggle, onModeChange, onNavigate, updateAvailable, onExit }) {
  const [showExitConfirm, setShowExitConfirm] = useState(false);

  useEffect(() => {
    if (!showExitConfirm) return undefined;
    const timer = window.setTimeout(() => setShowExitConfirm(false), 4000);
    return () => window.clearTimeout(timer);
  }, [showExitConfirm]);

  function expandFromMinimal() {
    if (mode === "minimal" && canToggle) {
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
            </div>
          )}
        </div>
        <Button
          variant="icon"
          className="sidebar-icon-toggle"
          onClick={(event) => {
            event.stopPropagation();
            if (canToggle) {
              onModeChange(mode === "fixed" ? "minimal" : "fixed");
            }
          }}
          disabled={!canToggle}
          disabledReason={!canToggle ? "Sidebar auto-collapses on smaller windows." : ""}
          title={mode === "fixed" ? "Collapse sidebar" : "Expand sidebar"}
          aria-label={mode === "fixed" ? "Collapse sidebar" : "Expand sidebar"}
        >
          {mode === "fixed" ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
        </Button>
      </div>

      <nav className="scrollable" aria-label="Desktop sections" onClick={(event) => event.stopPropagation()}>
        {views.map((view) => (
          <Button
            key={view.id}
            variant="ghost"
            className={activeView === view.id ? "active" : ""}
            onClick={() => onNavigate(view.id)}
            title={view.label}
            aria-label={view.label}
          >
            <span className="nav-mark"><NavIcon id={view.icon} /></span>
            {mode === "fixed" && <span>{view.label}</span>}
            {view.id === "update" && updateAvailable && <span className="nav-dot" aria-hidden="true" />}
          </Button>
        ))}
      </nav>

      <SidebarCurrentProfile state={state} mode={mode} />

      <div className={`sidebar-exit-section ${mode === "minimal" ? "minimal" : ""}`}>
        <Button
          variant="ghost"
          className={`sidebar-exit-btn ${mode === "minimal" ? "minimal" : ""} ${showExitConfirm ? "btn-disabled" : ""}`}
          onClick={(event) => {
            event.stopPropagation();
            if (mode === "minimal") {
              onExit?.();
              return;
            }
            setShowExitConfirm(true);
          }}
          title="Exit application"
          aria-label="Exit application"
        >
          <span className="nav-mark"><NavIcon id="exit" /></span>
          {mode === "fixed" && <span>Exit</span>}
        </Button>
        {mode === "fixed" && showExitConfirm ? (
          <div className="sidebar-exit-confirm" onClick={(event) => event.stopPropagation()}>
            <Button variant="ghost" onClick={() => setShowExitConfirm(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                setShowExitConfirm(false);
                onExit?.();
              }}
            >
              Confirm exit ✓
            </Button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function TopBar({ activeTitle, updateStatus, loading, onRefresh, onRestart }) {
  return (
    <header className="topbar desktop-topbar">
      <div className="topbar-meta">
        <span className="topbar-section-title">{activeTitle}</span>
        {updateStatus?.update_available && <Badge variant="warning">Update {updateStatus.latest_version || "available"}</Badge>}
      </div>
      <div className="top-actions">
        <ConfirmAction
          className="topbar-compact-btn"
          label="Restart"
          confirmLabel="Confirm restart ✓"
          onConfirm={onRestart}
          tone="danger"
        />
        <Button variant="primary" className="topbar-compact-btn" loading={loading} onClick={onRefresh} disabled={loading}>
          {loading ? "Refreshing" : "Refresh"}
        </Button>
      </div>
    </header>
  );
}

function AccountsTable({
  profiles,
  switching,
  activatedProfile,
  visibleColumns,
  sort,
  onSort,
  onSwitch,
  onOpenRowActions,
  onToggleEligibility,
  wideMode,
  compactMode,
  viewportSizeClass,
}) {
  const columnTitleByKey = {
    cur: "Status. Active = green dot, Inactive = gray dot.",
    h5: "5h means the five-hour usage window.",
    h5remain: "Remaining time until 5h usage resets.",
    h5reset: "Absolute time when 5h usage resets.",
    weeklyremain: "W means weekly window. Remaining time until weekly reset.",
    weeklyreset: "Absolute time when weekly usage resets.",
  };
  const columns = columnDefs
    .filter((column) => visibleColumns[column.key] && isColumnVisibleForViewport(column.key, viewportSizeClass))
    .map((column) => ({
      key: column.key,
      label: column.label,
      title: columnTitleByKey[column.key],
      colClassName: tableColumnLayout[column.key]?.colClassName || "",
      width: tableColumnLayout[column.key]?.width,
      className: ["email", "id", "added", "note", "h5remain", "h5reset", "weeklyremain", "weeklyreset"].includes(column.key)
        ? `${column.key === "email" ? "email-cell" : ""} ${column.key === "id" ? "id-cell" : ""} ${column.key === "added" ? "added-cell" : ""} ${column.key === "note" ? "note-cell" : ""} ${column.key === "h5remain" || column.key === "h5reset" || column.key === "weeklyremain" || column.key === "weeklyreset" ? "reset-cell" : ""}`.trim()
        : "",
      sortable: true,
      render: (profile) => {
        const quotaBlocked = (usageValue(profile, "usage_5h") ?? 1) <= 0 || (usageValue(profile, "usage_weekly") ?? 1) <= 0;
        const disableSwitch = profile.is_current || Boolean(switching);
        const noteText = String(profile.note || (profile.same_principal ? "same-principal" : "")).trim();
        switch (column.key) {
          case "cur":
            return <StatusDot active={profile.is_current} />;
          case "profile":
            return <strong className="profile-name">{profile.name}</strong>;
          case "email":
            return <span className="muted" title={profile.email_display}>{profile.email_display}</span>;
          case "h5":
            return <UsageCell row={profile} usageKey="usage_5h" />;
          case "h5remain":
            return (
              <span className="remain-value" title={fmtResetFull(profile.usage_5h?.resets_at)}>
                {fmtRemain(profile.usage_5h?.resets_at, true)}
              </span>
            );
          case "h5reset":
            return <span className="muted" title={fmtResetFull(profile.usage_5h?.resets_at)}>{fmtReset(profile.usage_5h?.resets_at)}</span>;
          case "weekly":
            return <UsageCell row={profile} usageKey="usage_weekly" />;
          case "weeklyremain":
            return (
              <span className="remain-value" title={fmtResetFull(profile.usage_weekly?.resets_at)}>
                {fmtRemain(profile.usage_weekly?.resets_at, true)}
              </span>
            );
          case "weeklyreset":
            return <span className="muted" title={fmtResetFull(profile.usage_weekly?.resets_at)}>{fmtReset(profile.usage_weekly?.resets_at)}</span>;
          case "plan":
            return (
              <Badge variant={planBadgeVariant(profile.plan_type)} className="plan-badge">
                {String(profile.plan_type || "free")}
              </Badge>
            );
          case "paid":
            return (
              <Badge variant={profile.is_paid ? "success" : "neutral"} className="paid-badge">
                {fmtPaid(profile.is_paid)}
              </Badge>
            );
          case "id":
            return <span className="muted id-value" title={profile.account_id || "-"}>{truncateAccountId(profile.account_id)}</span>;
          case "added":
            return <span className="muted" title={fmtSavedAtFull(profile.saved_at)}>{fmtSavedAt(profile.saved_at)}</span>;
          case "note":
            return <span className="muted" title={noteText || "-"}>{truncateNote(noteText)}</span>;
          case "auto":
            return (
              <span className="toggle">
                <ToggleSwitch
                  checked={!!profile.auto_switch_eligible}
                  onChange={(nextValue) => onToggleEligibility(profile.name, nextValue)}
                  ariaLabel={`Auto switch eligibility for ${profile.name}`}
                />
              </span>
            );
          case "actions":
            return (
              <div className={`actions-cell ${compactMode ? "compact" : ""}`} role="group" aria-label={`Actions for ${profile.name}`}>
                {compactMode ? (
                  <>
                    <Button
                      variant={quotaBlocked ? "danger" : "primary"}
                      className={`actions-menu-btn actions-switch-btn ${disableSwitch ? "btn-disabled" : ""}`}
                      loading={switching === profile.name}
                      disabled={disableSwitch}
                      onClick={() => onSwitch(profile.name)}
                      aria-label={`Switch to ${profile.name}`}
                      title={`Switch to ${profile.name}`}
                    >
                      ⇄
                    </Button>
                    <Button
                      className="actions-menu-btn"
                      data-row-actions={profile.name}
                      aria-label={`row actions ${profile.name}`}
                      title="Row actions"
                      onClick={() => onOpenRowActions(profile)}
                    >
                      ⋯
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      variant={quotaBlocked ? "danger" : "primary"}
                      className={disableSwitch ? "btn-disabled" : ""}
                      loading={switching === profile.name}
                      disabled={disableSwitch}
                      onClick={() => onSwitch(profile.name)}
                    >
                      {switching === profile.name ? "Switching" : "Switch"}
                    </Button>
                    <Button
                      className="actions-menu-btn"
                      data-row-actions={profile.name}
                      aria-label={`row actions ${profile.name}`}
                      title="Row actions"
                      onClick={() => onOpenRowActions(profile)}
                    >
                      ⋯
                    </Button>
                  </>
                )}
              </div>
            );
          default:
            return "-";
        }
      },
    }));

  return (
    <DataTable
      className={`profiles-data-table ${wideMode ? "wide-columns" : ""} ${compactMode ? "compact-columns" : ""}`.trim()}
      columns={columns}
      sort={sort}
      onSort={onSort}
      rows={profiles}
      rowKey={(profile) => profile.name}
      rowClassName={(profile) => buildProfileRowClassName({
        isCurrent: profile.is_current,
        isPending: switching === profile.name,
        isActivated: activatedProfile === profile.name,
      })}
      emptyState="No profiles available."
    />
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
                <StatusDot active={profile.is_current} />
                <span className="mobile-profile">{profile.name || "-"}</span>
              </div>
              <div className="mobile-actions">
                <Button
                  variant={quotaBlocked ? "danger" : "primary"}
                  className={switchDisabled ? "btn-disabled" : ""}
                  loading={switching === profile.name}
                  disabled={switchDisabled}
                  onClick={() => onSwitch(profile.name)}
                >
                  {switching === profile.name ? "Switching" : "Switch"}
                </Button>
                <Button className="actions-menu-btn" data-mobile-row-actions={profile.name} onClick={() => onOpenRowActions(profile)}>⋯</Button>
              </div>
            </div>
            <div className="mobile-email">{profile.email_display}</div>
            <div className="mobile-stats">
              <div className="mobile-stat"><span className="label" title="5h means the five-hour usage window.">5h</span><span className={h5Tone ? `usage-${h5Tone}` : "loading-text"}>{usagePercent(profile, "usage_5h")}</span></div>
              <div className="mobile-stat"><span className="label">Weekly</span><span className={weeklyTone ? `usage-${weeklyTone}` : "loading-text"}>{usagePercent(profile, "usage_weekly")}</span></div>
              <div className="mobile-stat"><span className="label" title="Remaining time until 5h usage resets.">5h remain</span><span>{fmtRemain(profile.usage_5h?.resets_at)}</span></div>
              <div className="mobile-stat"><span className="label" title="W means weekly window. Remaining time until weekly reset.">W remain</span><span>{fmtRemain(profile.usage_weekly?.resets_at)}</span></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProfilesView({
  state,
  switching,
  activatedProfile,
  onSwitch,
  onAddAccount,
  onImportProfiles,
  onExportProfiles,
  onRemoveAll,
  onOpenColumns,
  onOpenRowActions,
  onToggleEligibility,
  visibleColumns,
  sort,
  onSort,
  compactMode,
  viewportSizeClass,
}) {
  const profiles = sortRows(buildProfileRows(state), sort);
  const visibleColumnCount = Object.values(visibleColumns || {}).filter(Boolean).length;
  const wideMode = visibleColumnCount > 8;
  const activeColumnCount = columnDefs.filter((column) => visibleColumns?.[column.key]).length;
  const totalColumnCount = columnDefs.length;

  return (
    <section className="view profiles-view" data-testid="profiles-view">
      <div className="profiles-view-shell">
        <div className="accounts-toolbar">
          <div className="spacer" />
          <div className="accounts-actions">
            <Button variant="primary" onClick={onAddAccount}>Add Account</Button>
            <Button onClick={onImportProfiles}>Import</Button>
            <Button className="profiles-export-btn" onClick={onExportProfiles}>
              <span className="btn-label">Export</span>
            </Button>
            <ConfirmAction
              label="Remove all"
              confirmLabel="Confirm remove all ✓"
              tone="danger"
              onConfirm={onRemoveAll}
            />
            <Button className="columns-btn" onClick={onOpenColumns}>
              <span className="btn-label">Columns</span>
              <span className="columns-hidden-badge columns-count-badge" aria-label={`${activeColumnCount} of ${totalColumnCount} columns active`}>
                {activeColumnCount}/{totalColumnCount}
              </span>
            </Button>
          </div>
        </div>
        <div className={`table-wrap profiles-table-wrap scrollable scrollable-with-fade ${wideMode ? "wide-columns" : ""}`}>
          <AccountsTable
            profiles={profiles}
            switching={switching}
            activatedProfile={activatedProfile}
            visibleColumns={visibleColumns}
            wideMode={wideMode}
            compactMode={compactMode}
            viewportSizeClass={viewportSizeClass}
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

function AutoRefreshSettingsCard({ state, onSavePatch }) {
  const ui = state?.config?.ui || {};

  return (
    <SectionCard className="control-card control-card-full settings-card settings-refresh-card">
      <div className="group-title">Refresh rules</div>
      <div className="auto-refresh-sections">
        <section className="auto-refresh-section">
          <div className="auto-refresh-title-row">
            <h3>Current account refresh</h3>
            <span>Unit: seconds</span>
          </div>
          <div className="auto-refresh-row">
            <span className="setting-label">Enabled</span>
            <span className="toggle auto-refresh-toggle">
              <ToggleSwitch
                checked={!!ui.current_auto_refresh_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { current_auto_refresh_enabled: nextValue } })}
                ariaLabel="Enable current account refresh"
              />
            </span>
          </div>
          <div className="auto-refresh-control-surface">
            <div className="auto-refresh-inline-controls">
              <span className="setting-label auto-refresh-inline-label">Delay (seconds)</span>
              <StepperInput
                value={ui.current_refresh_interval_sec ?? 5}
                min={1}
                max={3600}
                unit="sec"
                onChange={(value) => onSavePatch({ ui: { current_refresh_interval_sec: value } })}
              />
            </div>
          </div>
        </section>
        <section className="auto-refresh-section">
          <div className="auto-refresh-title-row">
            <h3>All accounts refresh</h3>
            <span>Unit: minutes</span>
          </div>
          <div className="auto-refresh-row">
            <span className="setting-label">Enabled</span>
            <span className="toggle auto-refresh-toggle">
              <ToggleSwitch
                checked={!!ui.all_auto_refresh_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { all_auto_refresh_enabled: nextValue } })}
                ariaLabel="Enable all accounts refresh"
              />
            </span>
          </div>
          <div className="auto-refresh-control-surface">
            <div className="auto-refresh-inline-controls">
              <span className="setting-label auto-refresh-inline-label">Delay (minutes)</span>
              <StepperInput
                value={ui.all_refresh_interval_min ?? 5}
                min={1}
                max={60}
                unit="min"
                onChange={(value) => onSavePatch({ ui: { all_refresh_interval_min: value } })}
              />
            </div>
          </div>
        </section>
      </div>
    </SectionCard>
  );
}

function useCountdownText(dueAtText, dueAt) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return formatAutoSwitchCountdown(dueAtText, dueAt, now);
}

function AutoSwitchView({ state, onSavePatch, onOpenChainEdit, onRunSwitch, onRapidTest, onStopTests, onTestAutoSwitch, onAutoArrange }) {
  const autoState = state?.autoSwitch || {};
  const autoConfig = state?.config?.auto_switch || {};
  const countdownText = useCountdownText(autoState.pending_switch_due_at_text, autoState.pending_switch_due_at);
  const chainOrder = Array.isArray(state?.list?.profiles) ? state.list.profiles.map((row) => row.name) : [];
  const chainRows = sortRows(buildProfileRows(state), { key: "profile", dir: "asc" }).filter((row) => chainOrder.includes(row.name));
  const pendingSwitch = Boolean(autoState.pending_switch_due_at);
  const usageAverage = (key) => {
    const values = chainRows
      .map((row) => usageValue(row, key))
      .filter((value) => Number.isFinite(value));
    if (!values.length) return "-";
    return `${Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)}%`;
  };

  return (
    <section className="view autoswitch-view" data-testid="autoswitch-view">
      <SectionCard className={`card auto-switch-card ${pendingSwitch ? "armed" : ""}`}>
        <div className="auto-switch-head">
          <div className="k">Auto-switch rules</div>
          <div className={`auto-switch-countdown ${pendingSwitch ? "active pending" : "active idle"}`}>{countdownText}</div>
        </div>
        <div className="rules-grid">
          <div className="rules-col settings-card">
            <div className="rules-title">Execution</div>
            <div className="setting-row">
              <span className="setting-label">Enabled</span>
              <span className="toggle">
                <ToggleSwitch
                  checked={!!autoConfig.enabled}
                  onChange={(nextValue) => onSavePatch({ auto_switch: { enabled: nextValue } })}
                  ariaLabel="Enable auto switch"
                />
              </span>
            </div>
            <div className="setting-row metric inset-row">
              <span className="setting-label">Delay (seconds)</span>
              <StepperInput
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
                <div className={`v ${pendingSwitch ? "pending" : ""}`}>{countdownText}</div>
              </div>
            </div>
            <div className="exec-actions exec-actions-split">
              <div className="exec-actions-primary">
                <ConfirmAction
                  label="Run switch"
                  confirmLabel="Confirm run switch ✓"
                  tone="primary"
                  onConfirm={onRunSwitch}
                />
              </div>
              <div className="exec-actions-divider" aria-hidden="true" />
              <div className="exec-actions-secondary">
                <Button onClick={onRapidTest}>Rapid test</Button>
                <Button variant="dangerOutline" onClick={onStopTests}>Stop tests</Button>
                <Button onClick={onTestAutoSwitch}>Test auto switch</Button>
              </div>
            </div>
          </div>
          <div className="rules-col settings-card">
            <div className="rules-title">Selection Policy</div>
            <div className="setting-field">
              <div className="selection-head">
                <span className="setting-label">Ranking</span>
                <Button
                  variant="ghost"
                  onClick={onAutoArrange}
                  title="Automatically reorder the switch chain based on current ranking policy."
                >
                  Auto Arrange
                </Button>
              </div>
              <select value={autoConfig.ranking_mode || "balanced"} onChange={(event) => onSavePatch({ auto_switch: { ranking_mode: event.target.value } })}>
                <option value="balanced">balanced</option>
                <option value="max_5h">max_5h</option>
                <option value="max_weekly">max_weekly</option>
                <option value="manual">manual</option>
              </select>
            </div>
            <div className="metric-pair-grid">
              <div className="setting-row metric inset-row">
                <span className="setting-label">5h switch (%)</span>
                <StepperInput
                  value={autoConfig.thresholds?.h5_switch_pct ?? 20}
                  min={0}
                  max={100}
                  onChange={(value) => onSavePatch({ auto_switch: { thresholds: { h5_switch_pct: value } } })}
                />
              </div>
              <div className="setting-row metric inset-row">
                <span className="setting-label">Weekly switch (%)</span>
                <StepperInput
                  value={autoConfig.thresholds?.weekly_switch_pct ?? 20}
                  min={0}
                  max={100}
                  onChange={(value) => onSavePatch({ auto_switch: { thresholds: { weekly_switch_pct: value } } })}
                />
              </div>
            </div>
          </div>
        </div>
        <div className="chain-panel">
          <div className="chain-head">
            <div className="chain-title">Switch Chain Preview</div>
            <Button onClick={onOpenChainEdit}>Edit</Button>
          </div>
          <div className="chain-track-wrap scrollable">
            <div className="chain-track">
              {chainRows.length ? chainRows.map((row) => (
                <span key={row.name} className="chain-node">
                  <span className="chain-name">{row.name}</span>
                  <span className={`chain-metric progress-tone-${usageTone(usageValue(row, "usage_5h"))}`} title="5-hour usage">
                    5H {usagePercent(row, "usage_5h")}
                  </span>
                  <span className={`chain-metric progress-tone-${usageTone(usageValue(row, "usage_weekly"))}`} title="Weekly usage">
                    W {usagePercent(row, "usage_weekly")}
                  </span>
                </span>
              )) : <span className="muted">No profiles available.</span>}
            </div>
          </div>
          <div className="chain-key">
            <span title="5H means five-hour usage window">5H = 5-hour usage</span>
            {" · "}
            <span title="W means weekly usage window">W = weekly usage</span>
          </div>
        </div>
        <div className="autoswitch-hint-zone">
          <span>Accounts switch in chain order when a threshold is reached.</span>
          <div className="autoswitch-mini-stats" aria-label="Switch chain summary">
            <LabelValueRow label="Total accounts" value={chainRows.length || "-"} />
            <LabelValueRow label="Average 5H usage" value={usageAverage("usage_5h")} />
            <LabelValueRow label="Average weekly usage" value={usageAverage("usage_weekly")} />
          </div>
        </div>
      </SectionCard>
    </section>
  );
}

function NotificationsSettingsCard({ state, onNotify, onSavePatch }) {
  const notifications = state?.config?.notifications || {};

  return (
    <SectionCard className="control-card control-card-full notify-card settings-card">
      <div className="group-title">Notifications</div>
      <div className="setting-row inset-row">
        <span className="setting-label">Enable notifications</span>
        <span className="toggle">
          <ToggleSwitch
            checked={!!notifications.enabled}
            onChange={(nextValue) => onSavePatch({ notifications: { enabled: nextValue } })}
            ariaLabel="Enable notifications"
          />
        </span>
      </div>
      <div className="metric-pair-grid">
        <div className="setting-row metric inset-row">
          <span className="setting-label">Notify when 5h usage exceeds (%)</span>
          <StepperInput
            value={notifications.thresholds?.h5_warn_pct ?? 20}
            min={0}
            max={100}
            onChange={(value) => onSavePatch({ notifications: { thresholds: { h5_warn_pct: value } } })}
          />
        </div>
        <div className="setting-row metric inset-row">
          <span className="setting-label">Notify when weekly usage exceeds (%)</span>
          <StepperInput
            value={notifications.thresholds?.weekly_warn_pct ?? 20}
            min={0}
            max={100}
            onChange={(value) => onSavePatch({ notifications: { thresholds: { weekly_warn_pct: value } } })}
          />
        </div>
      </div>
      <div className="alarm-actions">
        <Button className="btn-block" type="button" onClick={onNotify}>Test notification</Button>
      </div>
    </SectionCard>
  );
}

function SettingsView({ state, onRestart, onKillAll, onToggleTheme, onToggleDebug, onNotify, onSavePatch }) {
  const ui = state?.config?.ui || {};
  const isWindows = window.codexAccountDesktop?.platform === "win32";
  const logsEnabled = !!ui.debug_mode;
  const themeMode = ui.theme || "auto";
  const platformName = window.codexAccountDesktop?.platform || navigator.platform || "unknown";

  return (
    <section className="view settings-view scrollable" data-testid="settings-view">
      <div className="settings-layout">
        <div className="controls-grid">
          <SectionCard className="control-card settings-card">
            <div className="group-title">Appearance</div>
            <div className="setting-row inset-row">
              <span className="setting-label">Theme mode</span>
              <strong>{themeMode}</strong>
            </div>
            <div className="settings-inline-actions">
              <Button className={themeMode !== "auto" ? "btn-active" : ""} onClick={onToggleTheme}>Cycle theme</Button>
              <Button className={logsEnabled ? "btn-active" : ""} onClick={onToggleDebug}>
                {logsEnabled ? "Logs on" : "Logs off"}
              </Button>
            </div>
          </SectionCard>
          <SectionCard className="control-card settings-card">
            <div className="group-title">Maintenance</div>
            <p className="muted">Restart reconnects the desktop panel to the local service without changing account data.</p>
            <p className="muted">Kill All stops managed Codex Account Manager background processes. Use it only when restart cannot recover the app.</p>
            <div className="settings-inline-actions">
              <ConfirmAction
                label="Restart"
                confirmLabel="Confirm restart ✓"
                tone="primary"
                onConfirm={onRestart}
              />
              <ConfirmAction
                label="Kill all"
                confirmLabel="Confirm kill all ✓"
                tone="danger"
                onConfirm={onKillAll}
              />
            </div>
          </SectionCard>
          <AutoRefreshSettingsCard state={state} onSavePatch={onSavePatch} />
          <NotificationsSettingsCard state={state} onNotify={onNotify} onSavePatch={onSavePatch} />
          {isWindows ? (
            <SectionCard className="control-card settings-card">
              <div className="group-title">Windows Integration</div>
              <div className="setting-row inset-row">
                <span className="setting-label" title="5H means the five-hour usage window.">Show current 5H usage on taskbar</span>
                <span className="toggle">
                  <ToggleSwitch
                    checked={!!ui.windows_taskbar_usage_enabled}
                    onChange={(nextValue) => onSavePatch({ ui: { windows_taskbar_usage_enabled: nextValue } })}
                    ariaLabel="Show current 5H usage on taskbar"
                  />
                </span>
              </div>
              <p className="muted">Adds a compact current 5H usage badge to the Windows taskbar button.</p>
            </SectionCard>
          ) : null}
        </div>
        <SectionCard className="control-card settings-card settings-system-card">
          <div className="group-title">System info</div>
          <div className="settings-system-grid">
            <LabelValueRow label="Platform" value={platformName} />
            <LabelValueRow label="Current refresh" value={ui.current_auto_refresh_enabled ? `${ui.current_refresh_interval_sec || 5}s` : "disabled"} />
            <LabelValueRow label="All refresh" value={ui.all_auto_refresh_enabled ? `${ui.all_refresh_interval_min || 5}m` : "disabled"} />
          </div>
        </SectionCard>
      </div>
    </section>
  );
}

function GuideView({ releaseNotes, onRefreshReleaseNotes }) {
  const notes = Array.isArray(releaseNotes?.releases) ? releaseNotes.releases : [];
  const latestTag = notes[0]?.tag || "No release notes loaded";
  const shortcuts = views.slice(0, 9);

  return (
    <section className="view guide-view">
      <div className="guide-layout">
        <div className="guide-quick">
          <SectionCard className="settings-card guide-quick-card">
            <div className="group-title">Quick start</div>
            <p className="muted">Use Add Account, Switch, Import, Export, and Auto Switch from the desktop shell.</p>
            <LabelValueRow label="Desktop parity" value="Electron mirrors the web panel behavior, dialogs, and table controls." />
            <LabelValueRow label="Latest release" value={latestTag} />
            <div className="settings-inline-actions">
              <Button onClick={onRefreshReleaseNotes}>Reload release notes</Button>
            </div>
          </SectionCard>

          <SectionCard className="settings-card guide-shortcuts-card">
            <div className="group-title">Key shortcuts</div>
            <div className="guide-shortcuts-table">
              {shortcuts.map((view) => (
                <div key={view.id} className="guide-shortcuts-row">
                  <span className="muted">{view.label}</span>
                  <code>{view.key}</code>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>

        <SectionCard className="settings-card guide-changelog-card">
          <div className="group-title">Changelog</div>
          <div className="release-sections scrollable scrollable-with-fade">
            {notes.length === 0 ? (
              <div className="muted">No release notes available.</div>
            ) : notes.slice(0, 10).map((note, index) => {
              const highlights = Array.isArray(note.highlights) && note.highlights.length
                ? note.highlights
                : String(note.body || "")
                  .split(/\n+/)
                  .map((item) => item.replace(/^\s*[-*]\s*/, "").trim())
                  .filter(Boolean)
                  .slice(0, 5);
              return (
                <details key={note.tag || note.title} className="release-section" open={index < 2}>
                  <summary className="release-section-head">
                    <span className="release-version-badge">{note.tag || "Release"}</span>
                    {note.published_at ? <span className="release-date">{formatReleaseDate(note.published_at)}</span> : null}
                  </summary>
                  <h3>{note.title || note.tag || "Release notes"}</h3>
                  {highlights.length ? (
                    <ul>
                      {highlights.map((item) => <li key={`${note.tag}-${item}`}>{item}</li>)}
                    </ul>
                  ) : (
                    <p className="muted">{String(note.body || "No highlights available.")}</p>
                  )}
                </details>
              );
            })}
          </div>
        </SectionCard>
      </div>
    </section>
  );
}

function UpdateView({ updateStatus, checking, onCheck, onRunUpdate }) {
  const updateAvailable = !!updateStatus?.update_available;

  return (
    <section className="view update-view">
      <div className="sparse-page-layout">
        <SectionCard className="settings-card update-panel">
          <div className="group-title">Update status</div>
          <LabelValueRow label="Current version" value={updateStatus?.current_version || "-"} />
          <LabelValueRow label="Latest version" value={updateStatus?.latest_version || "-"} />
          <LabelValueRow label="Status" value={updateStatus?.status_text || updateStatus?.status || "Unknown"} />
          {checking ? <div className="update-inline-loading" role="status" aria-live="polite">Checking for updates…</div> : null}
          <div className="settings-inline-actions">
            <Button loading={checking} onClick={onCheck} disabled={checking}>Check for updates</Button>
            <Button variant={updateAvailable ? "primary" : "secondary"} onClick={onRunUpdate} disabled={!updateAvailable || checking}>Update now</Button>
          </div>
        </SectionCard>
        <SectionCard className="settings-card sparse-secondary-card">
          <div className="group-title">Release stream</div>
          <p className="muted">Desktop updates include renderer fixes, runtime bootstrap improvements, and parity updates with the web panel.</p>
          <div className="tech-pill-row">
            <span className="chip chip-neutral">Electron</span>
            <span className="chip chip-neutral">Python Core</span>
            <span className="chip chip-neutral">Local API</span>
          </div>
        </SectionCard>
        <SectionCard className="settings-card sparse-bottom-fill">
          <div className="group-title">Recent update guidance</div>
          <p className="muted">When an update is available, run it from this page and keep this window open until status changes to ready.</p>
          <div className="update-guidance-list" aria-label="What gets updated">
            <LabelValueRow label="Renderer" value="Desktop screens, layout fixes, dialogs, and table behavior." />
            <LabelValueRow label="Python core" value="Account switching, usage collection, and local command logic." />
            <LabelValueRow label="Local API" value="The private service bridge used by the Electron shell." />
          </div>
        </SectionCard>
      </div>
    </section>
  );
}

function DebugView({ debugLogs, onExport }) {
  const [levelFilter, setLevelFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [showJump, setShowJump] = useState(false);
  const panelRef = useRef(null);

  const filteredLogs = useMemo(() => {
    const source = Array.isArray(debugLogs) ? debugLogs : [];
    const normalizedQuery = query.trim().toLowerCase();
    return source.filter((row) => {
      const level = String(row?.level || "info").toLowerCase();
      const normalizedLevel = level === "warning" ? "warn" : level;
      if (levelFilter !== "all" && normalizedLevel !== levelFilter) return false;
      if (!normalizedQuery) return true;
      const haystack = `${row?.ts || ""} ${row?.message || ""}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    }).slice(-240);
  }, [debugLogs, levelFilter, query]);

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    if (!showJump) {
      panel.scrollTop = panel.scrollHeight;
    }
  }, [filteredLogs, showJump]);

  function onPanelScroll(event) {
    const panel = event.currentTarget;
    const nearBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 48;
    setShowJump(!nearBottom);
  }

  function jumpToLatest() {
    const panel = panelRef.current;
    if (!panel) return;
    panel.scrollTop = panel.scrollHeight;
    setShowJump(false);
  }

  return (
    <section className="view debug-view">
      <div className="settings-inline-actions debug-actions">
        <Button onClick={onExport}>Export debug logs</Button>
      </div>
      <div className="debug-toolbar">
        <div className="debug-filter-chips" role="tablist" aria-label="Log level filter">
          {[
            { key: "all", label: "All" },
            { key: "info", label: "Info" },
            { key: "warn", label: "Warn" },
            { key: "error", label: "Error" },
          ].map((item) => (
            <Button
              key={item.key}
              type="button"
              className={`debug-chip ${levelFilter === item.key ? "active" : ""}`}
              onClick={() => setLevelFilter(item.key)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search logs"
          aria-label="Search logs"
        />
      </div>
      <div ref={panelRef} className="debug-log-panel scrollable scrollable-with-fade" onScroll={onPanelScroll}>
        {filteredLogs.length ? filteredLogs.map((row, index) => (
          <div key={`${row.ts || index}-${index}`} className={`debug-line log-${String(row.level || "info").toLowerCase()}`}>
            <span>{row.ts || "-"}</span>
            <strong>{formatLogLevel(row.level)}</strong>
            <span>{row.message || ""}</span>
          </div>
        )) : <div className="muted">No logs yet.</div>}
        {showJump ? (
          <Button type="button" className="debug-jump-latest" onClick={jumpToLatest}>
            Jump to latest
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function AboutView({ backendState, version, onOpenExternal }) {
  const backendUrl = String(backendState?.baseUrl || "http://127.0.0.1:4673/").trim();

  return (
    <section className="view about-view">
      <div className="sparse-page-layout">
        <SectionCard className="settings-card about-panel">
          <header className="about-identity">
            <img src={iconUrl} alt="" />
            <div>
              <h2>Codex Account Manager</h2>
              <p>Desktop account switching and usage monitoring for Codex profiles.</p>
              <span>Version {version || "unknown"}</span>
            </div>
          </header>
        </SectionCard>

        <SectionCard className="settings-card about-panel">
          <LabelValueRow label="Desktop shell" value="Electron renderer with Python backend" />
          <LabelValueRow label="Stable web panel" value="Still available through codex-account ui" />
          <LabelValueRow
            label="Backend"
            value={(
              <a
                className="about-backend-link"
                href={backendUrl}
                onClick={(event) => {
                  event.preventDefault();
                  onOpenExternal(backendUrl);
                }}
              >
                {backendUrl}
              </a>
            )}
          />
        </SectionCard>

        <SectionCard className="settings-card sparse-bottom-fill">
          <div className="group-title">Built with</div>
          <div className="tech-pill-row">
            <span className="chip chip-neutral">Electron</span>
            <span className="chip chip-neutral">React</span>
            <span className="chip chip-neutral">Python API</span>
            <span className="chip chip-neutral">Playwright Tests</span>
          </div>
        </SectionCard>
      </div>
    </section>
  );
}

function RuntimeSetupView({
  runtimeStatus,
  runtimeProgress,
  busy,
  onRetry,
  onInstallPython,
  onInstallCore,
  onStartBackend,
  onOpenExternal,
  onCopyDiagnostics,
}) {
  const phase = runtimeStatus?.phase || "checking_runtime";
  const pythonInstallUrl = runtimeStatus?.python?.installUrl;
  const errorMessages = Array.isArray(runtimeStatus?.errors) ? runtimeStatus.errors : [];
  const progressRows = Array.isArray(runtimeProgress) ? runtimeProgress : [];
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [copyState, setCopyState] = useState("");
  const autoResumeKeyRef = useRef("");
  const heading = phase === "python_missing" ? "Install Python"
    : phase === "service_starting" ? "Starting local service"
      : phase === "error" && runtimeStatus?.reason === "core_update_required" ? "Update Python Core"
        : "Set up Python Core";

  useEffect(() => {
    if (!copyState) return undefined;
    const timer = window.setTimeout(() => setCopyState(""), 1800);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const statusTone = phase === "error"
    ? "danger"
    : (phase === "service_starting" || busy || phase === "core_missing" || phase === "python_missing")
      ? "warning"
      : "success";
  const hasPython = Boolean(runtimeStatus?.python?.supported);
  const hasCore = Boolean(runtimeStatus?.core?.installed);
  const hasBackend = Boolean(runtimeStatus?.uiService?.running);

  useEffect(() => {
    const shouldAutoResume = !busy && phase !== "ready" && hasPython && hasCore && hasBackend;
    if (!shouldAutoResume) {
      autoResumeKeyRef.current = "";
      return undefined;
    }
    const signature = `${phase}:${runtimeStatus?.reason || ""}:${runtimeStatus?.core?.commandPath || ""}:${runtimeStatus?.uiService?.baseUrl || ""}`;
    if (autoResumeKeyRef.current === signature) {
      return undefined;
    }
    autoResumeKeyRef.current = signature;
    const timer = window.setTimeout(() => {
      onRetry?.();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    busy,
    hasBackend,
    hasCore,
    hasPython,
    onRetry,
    phase,
    runtimeStatus?.core?.commandPath,
    runtimeStatus?.reason,
    runtimeStatus?.uiService?.baseUrl,
  ]);

  const activeStep = !hasPython ? 0 : !hasCore ? 1 : !hasBackend ? 2 : 2;
  const stepRows = [
    {
      title: "Python runtime",
      detail: hasPython
        ? `Detected ${runtimeStatus?.python?.version || "supported"}`
        : phase === "python_missing"
          ? "Install Python 3.11+ first"
          : "Python version is unsupported",
      state: hasPython ? "done" : "current",
    },
    {
      title: "Install core",
      detail: hasCore
        ? `Core ${runtimeStatus?.core?.version || "detected"}`
        : busy
          ? "Installing Codex Account Manager core"
          : "Install Codex Account Manager core",
      state: hasCore ? "done" : (hasPython ? "current" : "todo"),
    },
    {
      title: "Start service",
      detail: hasBackend ? "Local API is reachable" : "Start the local background service",
      state: hasBackend ? "done" : (hasCore ? "current" : "todo"),
    },
  ];
  const summaryBits = [
    runtimeStatus?.python?.version ? `Python ${runtimeStatus.python.version}` : "Python missing",
    hasCore ? `Core ${runtimeStatus?.core?.version || "installed"}` : "Core missing",
    hasBackend ? "Backend online" : "Backend offline",
  ];
  const completedSteps = [hasPython, hasCore, hasBackend].filter(Boolean).length;
  const progressPercent = hasBackend
    ? 100
    : Math.min(
      99,
      Math.round(((completedSteps + (busy ? 0.5 : 0)) / stepRows.length) * 100),
    );
  const progressTone = phase === "error" ? "danger" : (busy ? "active" : "default");
  const progressWidthClass = `progress-width-${Math.max(0, Math.min(100, progressPercent))}`;
  const progressLabel = progressPercent === 100
    ? "Setup complete"
    : busy
      ? `${progressPercent}% complete · installing`
      : `${progressPercent}% complete`;
  const infoMessage = phase === "python_missing"
    ? "Python 3.11 or newer is required before the desktop app can continue."
    : phase === "core_missing"
      ? "Install the Python core to unlock the desktop app."
      : runtimeStatus?.reason === "backend_start_failed"
        ? "The Python core is installed, but the local background service could not start."
        : runtimeStatus?.reason === "core_update_required"
          ? "The detected Python core is too old for this desktop build."
          : phase === "service_starting"
            ? "The installer finished. The app is now starting the local service."
            : "The desktop shell needs the local Python core before the main UI can open.";
  const primaryAction = phase === "python_missing"
    ? {
      label: "Install Python",
      onClick: onInstallPython || (() => onOpenExternal(pythonInstallUrl)),
      disabled: busy || (!onInstallPython && !pythonInstallUrl),
    }
    : phase === "service_starting" || runtimeStatus?.reason === "backend_start_failed"
      ? { label: "Start Service", onClick: onStartBackend, disabled: busy }
      : { label: "Install Core", onClick: onInstallCore, disabled: busy };
  const showRetry = phase === "error" || phase === "core_missing" || phase === "python_missing";
  const diagnosticsSections = [
    {
      label: "Runtime",
      body: [
        `Phase: ${phase}`,
        `Reason: ${runtimeStatus?.reason || "-"}`,
        `Python: ${runtimeStatus?.python?.path || "not detected"}`,
        `Core: ${runtimeStatus?.core?.commandPath || "not installed"}`,
        `Backend: ${runtimeStatus?.uiService?.baseUrl || "http://127.0.0.1:4673/"}`,
      ],
    },
    errorMessages.length ? {
      label: "Errors",
      body: errorMessages.map((item) => `${item.code}: ${item.message}`),
    } : null,
    {
      label: "Progress",
      body: progressRows.length
        ? progressRows.map((entry) => `${entry.label || entry.type || "Step"}${entry.status ? ` (${entry.status})` : ""}${entry.message ? `: ${entry.message}` : ""}`)
        : ["No bootstrap output captured yet."],
    },
  ].filter(Boolean);

  async function handleCopyDiagnostics() {
    try {
      await onCopyDiagnostics();
      setCopyState("Copied");
    } catch (error) {
      setCopyState("Copy failed");
    }
  }

  return (
    <main className="desktop-shell runtime-shell" data-testid="runtime-setup-view">
      <section className={`runtime-stage ${detailsOpen ? "details-open" : ""}`}>
        <div className="runtime-card" data-testid="runtime-card">
          <header className="runtime-card-head">
            <div className="runtime-card-title">
              <span className="runtime-kicker">Setup Assistant</span>
              <h1>{heading}</h1>
              <p className="runtime-copy">{infoMessage}</p>
            </div>
            <div className={`runtime-status-pill ${statusTone}`}>{phase.replaceAll("_", " ")}</div>
          </header>
          <div className={`runtime-workspace ${detailsOpen ? "details-open" : ""}`}>
            <div className="runtime-main-panel">
              <div className="runtime-summary-row" aria-label="Runtime summary">
                {summaryBits.map((bit) => <span key={bit}>{bit}</span>)}
              </div>

              <section className="runtime-stepper" aria-label="Installer steps">
                {stepRows.map((step, index) => (
                  <article
                    key={step.title}
                    className={`runtime-step-item ${step.state} ${index === activeStep ? "active" : ""}`}
                  >
                    <div className="runtime-step-marker" aria-hidden="true">{index + 1}</div>
                    <div className="runtime-step-body">
                      <strong>{step.title}</strong>
                      <p>{step.detail}</p>
                    </div>
                  </article>
                ))}
              </section>

              <div className="runtime-footer">
                <section className="runtime-progress" aria-label="Overall setup progress">
                  <div className="runtime-progress-head">
                    <strong>Overall progress</strong>
                    <span data-testid="runtime-progress-label">{progressLabel}</span>
                  </div>
                  <div
                    className={`runtime-progress-bar ${progressTone}`}
                    data-testid="runtime-progress-bar"
                    aria-hidden="true"
                  >
                    <span className={progressWidthClass} />
                  </div>
                </section>

                <div className="runtime-action-row">
                  <Button
                    variant="primary"
                    loading={busy}
                    onClick={primaryAction.onClick}
                    disabled={primaryAction.disabled}
                  >
                    {primaryAction.label}
                  </Button>
                  <Button
                    type="button"
                    className="runtime-text-button btn-ghost"
                    onClick={() => setDetailsOpen((value) => !value)}
                    aria-expanded={detailsOpen}
                    data-testid="runtime-details-toggle"
                  >
                    {detailsOpen ? "Hide details" : "Show details"}
                  </Button>
                  {showRetry ? <Button onClick={onRetry} disabled={busy}>Retry</Button> : null}
                  {copyState ? <span className="runtime-copy-state" role="status" aria-live="polite">{copyState}</span> : null}
                </div>
              </div>
            </div>

            {detailsOpen ? (
              <section className="runtime-details" data-testid="runtime-details">
                <div className="runtime-details-head">
                  <strong>Diagnostics</strong>
                  <Button type="button" className="runtime-mini-button btn-ghost" onClick={handleCopyDiagnostics}>Copy logs</Button>
                </div>
                <div className="runtime-details-body" data-testid="runtime-details-body">
                  {diagnosticsSections.map((section) => (
                    <section key={section.label} className="runtime-detail-section">
                      <h2>{section.label}</h2>
                      <pre>{section.body.join("\n")}</pre>
                    </section>
                  ))}
                  <div className="runtime-detail-grid">
                    <div>
                      <label>Python</label>
                      <span>{runtimeStatus?.python?.version || "missing"}</span>
                      <small>{runtimeStatus?.python?.path || "Installer required"}</small>
                    </div>
                    <div>
                      <label>Core</label>
                      <span>{runtimeStatus?.core?.version || "not installed"}</span>
                      <small>{runtimeStatus?.core?.commandPath || "Bootstrap required"}</small>
                    </div>
                    <div>
                      <label>Backend</label>
                      <span>{runtimeStatus?.uiService?.running ? "running" : "offline"}</span>
                      <small>{runtimeStatus?.uiService?.baseUrl || "http://127.0.0.1:4673/"}</small>
                    </div>
                  </div>
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </section>
    </main>
  );
}

function AppContent() {
  const desktop = window.codexAccountDesktop;
  const { showToast } = useToast();
  const [activeView, setActiveView] = useState("profiles");
  const [viewportSizeClass, setViewportSizeClass] = useState(() => classifyWidth(window.innerWidth));
  const [sidebarMode, setSidebarMode] = useState("fixed");
  const [state, setState] = useState(null);
  const [backendState, setBackendState] = useState(null);
  const [releaseNotes, setReleaseNotes] = useState(null);
  const [updateStatus, setUpdateStatus] = useState(null);
  const [checkingUpdateStatus, setCheckingUpdateStatus] = useState(false);
  const [debugLogs, setDebugLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState("");
  const [activatedProfile, setActivatedProfile] = useState("");
  const [error, setError] = useState("");
  const [columnPrefs, setColumnPrefs] = useState(loadStoredColumns());
  const [sort, setSort] = useState({ key: "profile", dir: "asc" });
  const [modal, setModal] = useState(null);
  const [runtimeStatus, setRuntimeStatus] = useState({ phase: "checking_runtime", python: {}, core: {}, uiService: {}, errors: [] });
  const [runtimeProgress, setRuntimeProgress] = useState([]);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const switchControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const exportSelectionRef = useRef([]);
  const [chainOrder, setChainOrder] = useState([]);
  const stateRef = useRef(null);
  const backendStateRef = useRef(null);
  const configRevisionRef = useRef(null);
  const configSaveQueueRef = useRef(Promise.resolve());
  const pendingConfigSavesRef = useRef(0);
  const currentRefreshRunningRef = useRef(false);
  const allRefreshRunningRef = useRef(false);
  const autoSwitchRefreshRunningRef = useRef(false);
  const restartInFlightRef = useRef(false);
  const currentRefreshTimerRef = useRef(null);
  const allRefreshTimerRef = useRef(null);
  const autoSwitchStateTimerRef = useRef(null);
  const [, setClockTick] = useState(Date.now());

  const activeTitle = useMemo(() => views.find((view) => view.id === activeView)?.label || "Profiles", [activeView]);
  const updateAvailable = !!updateStatus?.update_available;
  const visibleColumns = useMemo(() => normalizeColumns(columnPrefs), [columnPrefs]);
  const compactMode = viewportSizeClass === "size-compact";
  const effectiveSidebarMode = compactMode ? "minimal" : sidebarMode;

  function notifySuccess(title, description = "") {
    showToast({ tone: "success", title, description });
  }

  useEffect(() => {
    if (!error) return;
    showToast({ tone: "danger", title: "Action failed", description: error });
  }, [error, showToast]);

  function openConfirmDialog({ title, body, confirmLabel = "Confirm", tone = "danger", onConfirm }) {
    setModal({
      type: "confirm-action",
      title,
      body,
      confirmLabel,
      tone,
      onConfirm,
    });
  }

  function applyDesktopState(nextState, { backend = undefined, chain = undefined } = {}) {
    setState(nextState);
    stateRef.current = nextState;
    configRevisionRef.current = Number(nextState?.config?._meta?.revision || configRevisionRef.current || 1);
    if (backend !== undefined) {
      setBackendState(backend);
      backendStateRef.current = backend;
    }
    if (chain !== undefined) {
      setChainOrder(Array.isArray(chain?.chain) ? chain.chain : []);
    }
    if (nextState?.config?.ui?.column_prefs) {
      setColumnPrefs(normalizeColumns(nextState.config.ui.column_prefs));
    }
  }

  function applyConfigState(nextConfig) {
    configRevisionRef.current = Number(nextConfig?._meta?.revision || configRevisionRef.current || 1);
    setState((current) => {
      if (!current) {
        return current;
      }
      const nextState = { ...current, config: nextConfig };
      stateRef.current = nextState;
      return nextState;
    });
    if (nextConfig?.ui?.column_prefs) {
      const normalized = normalizeColumns(nextConfig.ui.column_prefs);
      setColumnPrefs(normalized);
      saveStoredColumns(normalized);
    }
  }

  function applyUsageState(nextUsage) {
    setState((current) => {
      if (!current) {
        return current;
      }
      const nextState = { ...current, usage: nextUsage };
      stateRef.current = nextState;
      return nextState;
    });
  }

  function applyAutoSwitchState(nextAutoSwitch) {
    setState((current) => {
      if (!current) {
        return current;
      }
      const nextState = { ...current, autoSwitch: nextAutoSwitch };
      stateRef.current = nextState;
      return nextState;
    });
  }

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

  async function fetchBackendJson(path, { timeoutMs = 1200 } = {}) {
    const service = backendStateRef.current || runtimeStatus?.uiService || {};
    const baseUrl = service.baseUrl || joinBaseUrl(`http://${service.host || "127.0.0.1"}:${service.port || 4673}`, "/");
    const headers = {};
    if (service.token) {
      headers["X-Codex-Token"] = service.token;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(joinBaseUrl(baseUrl, path), {
        method: "GET",
        headers,
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.error?.message || `request failed: ${response.status}`);
      }
      return payload?.data || payload;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      if (pendingConfigSavesRef.current > 0) {
        try {
          await configSaveQueueRef.current;
        } catch (_) {}
      }
      const runtime = await desktop.getRuntimeStatus();
      setRuntimeStatus(runtime);
      if (!isRuntimeOperational(runtime)) {
        setState(null);
        setBackendState(null);
        return;
      }
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
      applyDesktopState(core, { backend, chain });
      setUpdateStatus(update);
      setReleaseNotes(notes);
      setDebugLogs(Array.isArray(logs?.logs) ? logs.logs : Array.isArray(logs) ? logs : []);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  async function refreshState() {
    await loadAll();
  }

  async function refreshCurrentUsage({ timeoutSec = 6 } = {}) {
    if (currentRefreshRunningRef.current || !isRuntimeOperational(runtimeStatus)) {
      return;
    }
    currentRefreshRunningRef.current = true;
    try {
      const usage = await request(`/api/usage-local/current?timeout=${encodeURIComponent(String(Math.max(1, timeoutSec)))}`, {});
      applyUsageState(usage);
    } catch (err) {
      setError((current) => current || `current usage: ${err?.message || String(err)}`);
    } finally {
      currentRefreshRunningRef.current = false;
    }
  }

  async function refreshAllAccountsUsage({ timeoutSec = 7 } = {}) {
    if (allRefreshRunningRef.current || !isRuntimeOperational(runtimeStatus)) {
      return;
    }
    allRefreshRunningRef.current = true;
    try {
      const usage = await request(`/api/usage-local?timeout=${encodeURIComponent(String(Math.max(1, timeoutSec)))}&force=true`, {});
      applyUsageState(usage);
    } catch (err) {
      setError((current) => current || `all usage: ${err?.message || String(err)}`);
    } finally {
      allRefreshRunningRef.current = false;
    }
  }

  async function refreshAutoSwitchState() {
    if (autoSwitchRefreshRunningRef.current || !isRuntimeOperational(runtimeStatus)) {
      return;
    }
    autoSwitchRefreshRunningRef.current = true;
    try {
      const autoSwitch = await request("/api/auto-switch/state", {});
      applyAutoSwitchState(autoSwitch);
      if (activeView === "autoswitch") {
        const chain = await request("/api/auto-switch/chain", {});
        setChainOrder(Array.isArray(chain?.chain) ? chain.chain : []);
      }
    } catch (_) {
      // Ignore polling errors; the next cycle will retry.
    } finally {
      autoSwitchRefreshRunningRef.current = false;
    }
  }

  async function retryRuntimeCheck() {
    setRuntimeBusy(true);
    setError("");
    try {
      const next = await desktop.retryRuntimeCheck();
      setRuntimeStatus(next);
      if (isRuntimeOperational(next)) {
        await loadAll();
      }
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function installCore() {
    setRuntimeBusy(true);
    setError("");
    setRuntimeProgress([]);
    try {
      const next = await desktop.installPythonCore();
      setRuntimeStatus(next);
      if (isRuntimeOperational(next)) {
        await loadAll();
      }
    } catch (err) {
      let detail = err?.message || String(err);
      if (/No handler registered/i.test(detail) && typeof desktop.debugIpc === "function") {
        try {
          const debug = await desktop.debugIpc();
          detail = `${detail}\nIPC debug: ${JSON.stringify(debug)}`;
        } catch (debugErr) {
          detail = `${detail}\nIPC debug failed: ${debugErr?.message || String(debugErr)}`;
        }
      }
      setError(detail);
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function installPythonRuntime() {
    if (typeof desktop.installPythonRuntime !== "function") {
      if (runtimeStatus?.python?.installUrl) {
        await desktop.openExternal(runtimeStatus.python.installUrl);
      }
      return;
    }
    setRuntimeBusy(true);
    setError("");
    setRuntimeProgress([]);
    try {
      const next = await desktop.installPythonRuntime();
      setRuntimeStatus(next);
      if (isRuntimeOperational(next)) {
        await loadAll();
      }
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function startBackendService() {
    setRuntimeBusy(true);
    setError("");
    try {
      const next = await desktop.startBackendService();
      setRuntimeStatus(next);
      if (isRuntimeOperational(next)) {
        await loadAll();
      }
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function copyRuntimeDiagnostics() {
    return desktop.copyRuntimeDiagnostics();
  }

  async function saveUiPatch(patch) {
    if (!patch || typeof patch !== "object") {
      return stateRef.current?.config || null;
    }

    const optimisticConfig = deepMerge(stateRef.current?.config || {}, patch);
    applyConfigState(optimisticConfig);

    pendingConfigSavesRef.current += 1;
    const executeSave = async () => {
      const payload = deepMerge({}, patch);
      if (Number.isFinite(Number(configRevisionRef.current))) {
        payload.base_revision = Number(configRevisionRef.current);
      }
      try {
        const nextConfig = await request("/api/ui-config", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        applyConfigState(nextConfig);
        return nextConfig;
      } catch (error) {
        const message = String(error?.message || error);
        if (/Config changed elsewhere/i.test(message)) {
          const liveConfig = await request("/api/ui-config", {});
          applyConfigState(liveConfig);
          const retryPayload = deepMerge({}, patch);
          if (Number.isFinite(Number(configRevisionRef.current))) {
            retryPayload.base_revision = Number(configRevisionRef.current);
          }
          const retriedConfig = await request("/api/ui-config", {
            method: "POST",
            body: JSON.stringify(retryPayload),
          });
          applyConfigState(retriedConfig);
          return retriedConfig;
        }
        try {
          const liveConfig = await request("/api/ui-config", {});
          applyConfigState(liveConfig);
        } catch (_) {}
        throw error;
      } finally {
        pendingConfigSavesRef.current = Math.max(0, pendingConfigSavesRef.current - 1);
      }
    };

    const run = configSaveQueueRef.current.then(executeSave);
    configSaveQueueRef.current = run.catch(() => null);
    return run;
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
    setState((current) => {
      const nextState = applyProfileSelection(current, target);
      stateRef.current = nextState;
      return nextState;
    });
    try {
      const next = await switchControllerRef.current.switchProfile(target);
      applyDesktopState(next);
      setActivatedProfile(target);
      notifySuccess("Profile switched", `Current profile: ${target}`);
      setTimeout(() => setActivatedProfile((current) => (current === target ? "" : current)), 1100);
    } catch (err) {
      loadAll().catch(() => {});
      setError(err?.message || String(err));
    } finally {
      setSwitching("");
    }
  }

  async function testNotification() {
    setError("");
    try {
      await desktop.testNotification();
      notifySuccess("Notification sent", "A test desktop notification was triggered.");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function executeRestartUiService() {
    if (restartInFlightRef.current) {
      return;
    }
    restartInFlightRef.current = true;
    setLoading(true);
    setError("");
    let reloadAfterMs = 1200;
    let previousHealthVersion = "";
    try {
      try {
        const initialHealth = await fetchBackendJson(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
        previousHealthVersion = String(initialHealth?.version || "").trim();
      } catch (_) {}
      try {
        const response = await request("/api/system/restart", { method: "POST", body: JSON.stringify({}) });
        reloadAfterMs = Math.max(400, Number(response?.reload_after_ms || 1200));
      } catch (err) {
        const message = String(err?.message || err);
        if (!/Failed to fetch|network/i.test(message)) {
          throw err;
        }
      }
      setError("Restarting UI service...");
      await waitForServiceRestart({
        previousVersion: previousHealthVersion,
        reloadAfterMs,
        wait: waitMs,
        fetchHealth: () => fetchBackendJson(`/api/health?r=${Date.now()}`, { timeoutMs: 900 }),
      });
      await loadAll();
      setError("");
      notifySuccess("Service restarted", "The local UI service is ready.");
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      restartInFlightRef.current = false;
      setLoading(false);
    }
  }

  function restartUiService() {
    return executeRestartUiService();
  }

  async function executeKillAll() {
    try {
      await request("/api/system/kill-all", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
      notifySuccess("Processes stopped", "All managed background processes were stopped.");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  function killAll() {
    return executeKillAll();
  }

  function requestExit() {
    return executeKillAll();
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
    setCheckingUpdateStatus(true);
    try {
      const next = await request("/api/app-update-status?force=true", {});
      setUpdateStatus(next);
      setActiveView("update");
      notifySuccess("Update check complete", next?.status_text || "Status refreshed.");
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setCheckingUpdateStatus(false);
    }
  }

  async function runUpdate() {
    try {
      const next = await request("/api/system/update", { method: "POST", body: JSON.stringify({}) });
      setUpdateStatus(next.update_status || updateStatus);
      await loadAll();
      setActiveView("update");
      notifySuccess("Update started", "The update command has been sent.");
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
      notifySuccess("Debug export ready", "Saved desktop debug snapshot.");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function openColumnsModal() {
    setModal({ type: "columns" });
  }

  async function openRowActions(profile) {
    if (!profile?.name) return;
    setModal({
      type: "row-actions",
      profile: {
        name: profile.name,
        email: profile.email_display || profile.email || "",
        accountId: profile.account_id || "",
      },
    });
  }

  async function copyToClipboard(label, value) {
    const text = String(value || "").trim();
    if (!text) {
      notifySuccess("Nothing to copy", `${label} is empty for this profile.`);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      notifySuccess("Copied", `${label} copied to clipboard.`);
    } catch (_) {
      setError(`Unable to copy ${label.toLowerCase()} to clipboard.`);
    }
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

  async function toggleEligibility(name, eligible) {
    try {
      await request("/api/auto-switch/account-eligibility", {
        method: "POST",
        body: JSON.stringify({ name, eligible }),
      });
      setState((current) => {
        if (!current?.list?.profiles) {
          return current;
        }
        const nextState = {
          ...current,
          list: {
            ...current.list,
            profiles: current.list.profiles.map((row) => (
              row.name === name ? { ...row, auto_switch_eligible: eligible } : row
            )),
          },
        };
        stateRef.current = nextState;
        return nextState;
      });
      refreshAutoSwitchState().catch(() => {});
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function runRapidTest() {
    try {
      await request("/api/auto-switch/rapid-test", { method: "POST", body: JSON.stringify({}) });
      await Promise.all([
        refreshAutoSwitchState(),
        refreshCurrentUsage({ timeoutSec: 8 }),
      ]);
      notifySuccess("Rapid test started");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function runAutoSwitch() {
    try {
      await request("/api/auto-switch/run-switch", { method: "POST", body: JSON.stringify({}) });
      await Promise.all([
        refreshAutoSwitchState(),
        refreshCurrentUsage({ timeoutSec: 8 }),
      ]);
      notifySuccess("Switch command sent");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function stopTests() {
    try {
      await request("/api/auto-switch/stop-tests", { method: "POST", body: JSON.stringify({}) });
      await refreshAutoSwitchState();
      notifySuccess("Tests stopped");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function testAutoSwitch() {
    try {
      await request("/api/auto-switch/test", { method: "POST", body: JSON.stringify({ timeout_sec: 30 }) });
      await Promise.all([
        refreshAutoSwitchState(),
        refreshCurrentUsage({ timeoutSec: 8 }),
      ]);
      notifySuccess("Auto-switch test started");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  async function autoArrange() {
    try {
      const next = await request("/api/auto-switch/auto-arrange", { method: "POST", body: JSON.stringify({}) });
      setChainOrder(Array.isArray(next?.chain) ? next.chain : []);
      refreshAutoSwitchState().catch(() => {});
      notifySuccess("Chain reordered");
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
      notifySuccess("Profile added");
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
    notifySuccess("Import applied");
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
    openConfirmDialog({
      title: "Remove profile",
      body: `Remove profile "${name}"?`,
      confirmLabel: "Remove",
      tone: "danger",
      onConfirm: async () => {
        await request("/api/local/remove", { method: "POST", body: JSON.stringify({ name }) });
        await loadAll();
      },
    });
  }

  async function handleRemoveAll() {
    try {
      await request("/api/local/remove-all", { method: "POST", body: JSON.stringify({}) });
      await loadAll();
      notifySuccess("Profiles removed", "All saved profiles were removed.");
    } catch (err) {
      setError(err?.message || String(err));
    }
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
    notifySuccess("Export ready", "The selected profiles were exported.");
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
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    backendStateRef.current = backendState;
  }, [backendState]);

  useEffect(() => {
    configRevisionRef.current = Number(state?.config?._meta?.revision || configRevisionRef.current || 1);
  }, [state?.config?._meta?.revision]);

  useEffect(() => {
    loadAll();
    const classList = document.body.classList;
    const applyViewportClasses = (width, height) => {
      const widthClass = classifyWidth(width);
      const heightClass = classifyHeight(height);
      classList.remove(...WIDTH_CLASS_NAMES, ...HEIGHT_CLASS_NAMES);
      classList.add(widthClass, heightClass);
      setViewportSizeClass(widthClass);
    };
    const observedRoot = document.documentElement;
    const syncViewportClasses = () => {
      applyViewportClasses(
        observedRoot?.clientWidth || window.innerWidth,
        observedRoot?.clientHeight || window.innerHeight,
      );
    };
    let resizeObserver = null;
    if (typeof ResizeObserver === "function") {
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries?.[0];
        if (!entry) return;
        applyViewportClasses(entry.contentRect.width, entry.contentRect.height);
      });
      resizeObserver.observe(observedRoot);
    } else {
      window.addEventListener("resize", syncViewportClasses);
    }
    syncViewportClasses();
    const offNavigate = desktop.onNavigate((view) => setActiveView(normalizeViewId(view)));
    const offSidebar = desktop.onToggleSidebar(() => {
      if (!document.body.classList.contains("size-compact")) {
        setSidebarMode((mode) => (mode === "fixed" ? "minimal" : "fixed"));
      }
    });
    const offRuntime = desktop.onRuntimeStatus((status) => {
      setRuntimeStatus(status);
      if (isRuntimeOperational(status)) {
        loadAll().catch(() => {});
      }
    });
    const offProgress = desktop.onRuntimeProgress((progress) => {
      setRuntimeProgress((current) => [...current, progress]);
    });
    return () => {
      offNavigate?.();
      offSidebar?.();
      offRuntime?.();
      offProgress?.();
      if (resizeObserver) resizeObserver.disconnect();
      else window.removeEventListener("resize", syncViewportClasses);
      classList.remove(...WIDTH_CLASS_NAMES, ...HEIGHT_CLASS_NAMES);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setClockTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (currentRefreshTimerRef.current) {
      window.clearInterval(currentRefreshTimerRef.current);
      currentRefreshTimerRef.current = null;
    }
    if (!isRuntimeOperational(runtimeStatus)) {
      return undefined;
    }
    const intervalMs = getCurrentRefreshIntervalMs(state?.config?.ui || {});
    if (!intervalMs) {
      return undefined;
    }
    currentRefreshTimerRef.current = window.setInterval(() => {
      const intervalSec = Math.max(1, Math.round(intervalMs / 1000));
      refreshCurrentUsage({ timeoutSec: Math.max(2, Math.min(12, intervalSec + 2)) }).catch(() => {});
    }, intervalMs);
    return () => {
      if (currentRefreshTimerRef.current) {
        window.clearInterval(currentRefreshTimerRef.current);
        currentRefreshTimerRef.current = null;
      }
    };
  }, [runtimeStatus?.phase, state?.config?.ui?.current_auto_refresh_enabled, state?.config?.ui?.current_refresh_interval_sec]);

  useEffect(() => {
    if (allRefreshTimerRef.current) {
      window.clearInterval(allRefreshTimerRef.current);
      allRefreshTimerRef.current = null;
    }
    if (!isRuntimeOperational(runtimeStatus)) {
      return undefined;
    }
    const intervalMs = getAllRefreshIntervalMs(state?.config?.ui || {});
    if (!intervalMs) {
      return undefined;
    }
    allRefreshTimerRef.current = window.setInterval(() => {
      refreshAllAccountsUsage({ timeoutSec: 7 }).catch(() => {});
    }, intervalMs);
    return () => {
      if (allRefreshTimerRef.current) {
        window.clearInterval(allRefreshTimerRef.current);
        allRefreshTimerRef.current = null;
      }
    };
  }, [runtimeStatus?.phase, state?.config?.ui?.all_auto_refresh_enabled, state?.config?.ui?.all_refresh_interval_min]);

  useEffect(() => {
    if (autoSwitchStateTimerRef.current) {
      window.clearInterval(autoSwitchStateTimerRef.current);
      autoSwitchStateTimerRef.current = null;
    }
    if (!isRuntimeOperational(runtimeStatus)) {
      return undefined;
    }
    autoSwitchStateTimerRef.current = window.setInterval(() => {
      refreshAutoSwitchState().catch(() => {});
    }, 1000);
    return () => {
      if (autoSwitchStateTimerRef.current) {
        window.clearInterval(autoSwitchStateTimerRef.current);
        autoSwitchStateTimerRef.current = null;
      }
    };
  }, [runtimeStatus?.phase, activeView]);

  useEffect(() => {
    if (activeView === "guide") loadReleaseNotes().catch(() => {});
    if (activeView === "debug") loadDebugLogs().catch(() => {});
    if (activeView === "update") loadAll().catch(() => {});
  }, [activeView]);

  if (!isRuntimeOperational(runtimeStatus)) {
    return (
      <RuntimeSetupView
        runtimeStatus={runtimeStatus}
        runtimeProgress={runtimeProgress}
        busy={runtimeBusy}
        onRetry={retryRuntimeCheck}
        onInstallPython={installPythonRuntime}
        onInstallCore={installCore}
        onStartBackend={startBackendService}
        onOpenExternal={(url) => desktop.openExternal(url)}
        onCopyDiagnostics={copyRuntimeDiagnostics}
      />
    );
  }

  return (
    <main className={`desktop-shell sidebar-${effectiveSidebarMode}`} data-testid="electron-renderer">
      <Sidebar
        state={state}
        activeView={activeView}
        mode={effectiveSidebarMode}
        canToggle={!compactMode}
        onModeChange={setSidebarMode}
        onNavigate={(view) => setActiveView(normalizeViewId(view))}
        updateAvailable={updateAvailable}
        onExit={requestExit}
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
            compactMode={compactMode}
            viewportSizeClass={viewportSizeClass}
            onSort={(key) => setSort((current) => ({ key, dir: current.key === key && current.dir === "asc" ? "desc" : "asc" }))}
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
        {activeView === "settings" && <SettingsView state={state} onRestart={restartUiService} onKillAll={killAll} onToggleTheme={toggleTheme} onToggleDebug={toggleDebug} onNotify={testNotification} onSavePatch={saveUiPatch} />}
        {activeView === "guide" && <GuideView releaseNotes={releaseNotes} onRefreshReleaseNotes={() => loadReleaseNotes(true).catch(() => {})} />}
        {activeView === "update" && <UpdateView updateStatus={updateStatus} checking={checkingUpdateStatus || loading} onCheck={checkForUpdates} onRunUpdate={runUpdate} />}
        {activeView === "debug" && <DebugView debugLogs={debugLogs} onExport={onExportDebug} />}
        {activeView === "about" && <AboutView backendState={backendState} version={updateStatus?.current_version} onOpenExternal={(url) => desktop.openExternal(url)} />}
        {error ? <div className="workspace-error" role="alert">{error}</div> : null}
      </div>

      {modal?.type === "confirm-action" && (
        <Dialog
          title={modal.title || "Confirm action"}
          size="sm"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={() => setModal(null)}>Cancel</Button>
              <Button
                variant={modal.tone === "warning" ? "warning" : "danger"}
                onClick={() => {
                  const onConfirm = modal.onConfirm;
                  setModal(null);
                  Promise.resolve(onConfirm?.()).catch((err) => setError(err?.message || String(err)));
                }}
              >
                {modal.confirmLabel || "Confirm"}
              </Button>
            </>
          )}
        >
          <p>{modal.body || "Are you sure you want to continue?"}</p>
        </Dialog>
      )}

      {modal?.type === "columns" && (
        <Dialog
          title="Table columns"
          size="md"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={() => { setColumnPrefs(defaultColumns); saveStoredColumns(defaultColumns); setModal(null); }}>Reset defaults</Button>
              <Button variant="primary" onClick={() => setModal(null)}>Done</Button>
            </>
          )}
        >
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
        </Dialog>
      )}

      {modal?.type === "row-actions" && (
        <Dialog title="Row actions" size="sm" onClose={() => setModal(null)} footer={<Button onClick={() => setModal(null)}>Done</Button>}>
          <LabelValueRow label="Profile" value={modal.profile?.name || "-"} />
          <div className="settings-inline-actions">
            <Button onClick={() => { setModal(null); handleRename(modal.profile?.name).catch((e) => setError(e?.message || String(e))); }}>Edit</Button>
            <Button onClick={() => copyToClipboard("Email", modal.profile?.email)}>Copy email</Button>
            <Button onClick={() => copyToClipboard("ID", modal.profile?.accountId)}>Copy ID</Button>
            <Button variant="danger" onClick={() => { setModal(null); handleRemove(modal.profile?.name); }}>Remove account</Button>
          </div>
        </Dialog>
      )}

      {modal?.type === "add-account" && (
        <Dialog title="Add account" size="md" onClose={() => setModal(null)} footer={<Button onClick={() => setModal(null)}>Close</Button>}>
          <div className="modal-form">
            <label>Profile name</label>
            <input value={modal.name} onChange={(event) => setModal((current) => ({ ...current, name: event.target.value }))} placeholder="work" />
            <label>Login mode</label>
            <select value={modal.mode} onChange={(event) => setModal((current) => ({ ...current, mode: event.target.value }))}>
              <option value="device">Device Login</option>
              <option value="normal">Normal Login</option>
            </select>
            <div className="settings-inline-actions">
              <Button variant="primary" onClick={() => startAddAccount(modal.mode, modal.name).catch((e) => setError(e?.message || String(e)))}>Start</Button>
            </div>
            {modal.session && (
              <div className="modal-card-inline">
                <div><label>Status</label><strong>{modal.session.status || "-"}</strong></div>
                <div><label>Login URL</label><strong>{modal.session.url || "-"}</strong></div>
                <div><label>Code</label><strong>{modal.session.code || "-"}</strong></div>
              </div>
            )}
          </div>
        </Dialog>
      )}

      {modal?.type === "export" && (
        <Dialog
          title="Export profiles"
          size="lg"
          onClose={() => setModal(null)}
          footer={<Button variant="primary" onClick={() => handleExportProfiles(modal.selected || [], modal.filename || "profiles").catch((e) => setError(e?.message || String(e)))}>Export selected</Button>}
        >
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
        </Dialog>
      )}

      {modal?.type === "import" && (
        <Dialog
          title="Import profiles"
          size="sm"
          onClose={() => setModal(null)}
          footer={(
            <>
              <input
                ref={fileInputRef}
                className="hidden-file-input"
                type="file"
                accept=".camzip,application/zip"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) importAnalyze(file).catch((err) => setError(err?.message || String(err)));
                  event.target.value = "";
                }}
              />
              <Button onClick={() => fileInputRef.current?.click()}>Choose archive</Button>
            </>
          )}
        >
          <p>Imported data may grant account access. Keep exported files private.</p>
          <Button variant="primary" onClick={() => fileInputRef.current?.click()}>Analyze import</Button>
        </Dialog>
      )}

      {modal?.type === "import-review" && (
        <Dialog title="Import review" size="lg" onClose={() => setModal(null)} footer={<Button variant="primary" onClick={() => applyImport(modal.analysis, modal.selections || []).catch((e) => setError(e?.message || String(e)))}>Apply import</Button>}>
          <LabelValueRow label="Archive" value={modal.file?.name || "uploaded file"} />
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
        </Dialog>
      )}

      {modal?.type === "chain-edit" && (
        <Dialog
          title="Edit switch chain"
          size="lg"
          onClose={() => setModal(null)}
          footer={<Button variant="primary" onClick={() => { request("/api/auto-switch/chain", { method: "POST", body: JSON.stringify({ chain: modal.chain || [] }) }).then(() => loadAll()).catch((e) => setError(e?.message || String(e))); setModal(null); }}>Save</Button>}
        >
          <p>Drag order is simplified to up/down controls in the desktop shell.</p>
          <div className="chain-list">
            {(modal.chain || []).map((name, index) => (
              <div key={name} className="chain-row">
                <strong>{name}</strong>
                <div className="settings-inline-actions">
                  <Button disabled={index === 0} onClick={() => setModal((current) => {
                    const next = [...current.chain];
                    [next[index - 1], next[index]] = [next[index], next[index - 1]];
                    return { ...current, chain: next };
                  })}>Up</Button>
                  <Button disabled={index === (modal.chain || []).length - 1} onClick={() => setModal((current) => {
                    const next = [...current.chain];
                    [next[index + 1], next[index]] = [next[index], next[index + 1]];
                    return { ...current, chain: next };
                  })}>Down</Button>
                </div>
              </div>
            ))}
          </div>
        </Dialog>
      )}
    </main>
  );
}

function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
}

createRoot(document.getElementById("root")).render(<App />);
