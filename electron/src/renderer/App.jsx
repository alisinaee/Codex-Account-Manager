import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import iconUrl from "../../assets/codex-account-manager.svg";
import "./styles.css";
import {
  AboutIcon,
  ArrowRightIcon,
  AutoSwitchIcon,
  DebugIcon,
  DialogCloseIcon,
  DoorClosedIcon,
  GuideIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  ProfilesIcon,
  SettingsIcon,
  ThemeAutoIcon,
  ThemeDarkIcon,
  ThemeLightIcon,
  UpdateIcon,
} from "./icon-pack.jsx";
import {
  buildSwitchAnimationPreview,
  buildRowsByNameOrder,
  buildSwitchRowMotionPlans,
  buildProfileRowClassName,
  createSwitchController,
  SWITCH_ROW_CLEANUP_BUFFER_MS,
  SWITCH_ROW_MOTION_MS,
  usageTone,
} from "./switch-state.mjs";
import { appendSessionToken } from "./request-paths.mjs";
import { refreshProfilesAfterMutation } from "./post-mutation-refresh.mjs";
import { buildDesktopLogEntry, mergeDebugLogs } from "./debug-logs.mjs";
import SettingsView, { SystemInfoSettingsCard } from "./SettingsView.jsx";
import {
  buildProfileRows,
  buildSidebarCurrentProfile,
  usagePercentNumber,
} from "./view-model.mjs";
import {
  arcDasharray,
  clampPercent,
  clampProfileColumnWidthPx,
  buildProfileColumnWidths,
  formatFullDateFromSeconds,
  formatFullDateFromValue,
  formatShortDateFromSeconds,
  formatShortDateFromValue,
  getProfileColumnResizeBounds,
  isProfileColumnResizable,
  normalizeProfileColumnWidthOverrides,
  remainToneFromResetEpochSeconds,
  resolveProfileColumnWidths,
  truncateAccountId,
  truncateNote,
  usageColor,
} from "./table-layout.mjs";
import {
  buildDesktopSwitchOptions,
  deepMerge,
  formatUsageRefreshError,
  formatAutoSwitchCountdown,
  getAllRefreshIntervalMs,
  getCurrentRefreshIntervalMs,
  isTimeoutErrorMessage,
  shouldRunStartupAllAccountsRefresh,
  waitForServiceRestart,
} from "./parity.mjs";
import { triggerBlobDownload } from "./download-utils.mjs";
import { getErrorBannerCountdownSeconds } from "./error-banner.mjs";
import { mergeUsagePayload } from "./usage-merge.mjs";
import { getNextThemeMode, normalizeThemeMode, watchThemePreference } from "./theme.mjs";
import Badge from "./components/Badge.jsx";
import Button from "./components/Button.jsx";
import ConfirmAction from "./components/ConfirmAction.jsx";
import DataTable from "./components/DataTable.jsx";
import Dialog from "./components/Dialog.jsx";
import { SettingCopy, SettingsCardShell, SettingsSubsection } from "./components/SettingsCardShell.jsx";
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

function cycleViewId(currentViewId, step = 1) {
  const total = views.length;
  if (!total) return "profiles";
  const normalizedCurrent = normalizeViewId(currentViewId);
  const currentIndex = views.findIndex((view) => view.id === normalizedCurrent);
  const startIndex = currentIndex >= 0 ? currentIndex : 0;
  const direction = Number(step) < 0 ? -1 : 1;
  const nextIndex = (startIndex + direction + total) % total;
  return views[nextIndex]?.id || "profiles";
}

function shortcutModifierLabel(isMacDesktop = false) {
  return isMacDesktop ? "Cmd" : "Ctrl";
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

const COLUMN_WIDTH_RESIZE_ENABLED_PREF_KEY = "codex_table_column_width_resize_enabled";
const COLUMN_WIDTH_OVERRIDES_PREF_KEY = "codex_table_column_width_overrides";

function normalizeColumnWidthResizeEnabled(value) {
  return value === true;
}

function loadStoredColumnWidthResizeEnabled() {
  try {
    return normalizeColumnWidthResizeEnabled(localStorage.getItem(COLUMN_WIDTH_RESIZE_ENABLED_PREF_KEY) === "1");
  } catch (_) {
    return false;
  }
}

function saveStoredColumnWidthResizeEnabled(enabled) {
  try {
    localStorage.setItem(COLUMN_WIDTH_RESIZE_ENABLED_PREF_KEY, enabled ? "1" : "0");
  } catch (_) {}
}

function loadStoredColumnWidthOverrides() {
  try {
    return normalizeProfileColumnWidthOverrides(JSON.parse(localStorage.getItem(COLUMN_WIDTH_OVERRIDES_PREF_KEY) || "{}"));
  } catch (_) {
    return {};
  }
}

function saveStoredColumnWidthOverrides(overrides) {
  try {
    localStorage.setItem(COLUMN_WIDTH_OVERRIDES_PREF_KEY, JSON.stringify(normalizeProfileColumnWidthOverrides(overrides)));
  } catch (_) {}
}

const WINDOWS_SWITCH_RESTART_DIALOG_PREF_KEY = "codex_windows_switch_restart_dialog_suppressed";
const DEBUG_CAPTURE_PREF_KEY = "codex_debug_capture_enabled";
const ERROR_BANNER_AUTO_DISMISS_MS = 30_000;

function loadWindowsSwitchRestartDialogPreference() {
  try {
    return localStorage.getItem(WINDOWS_SWITCH_RESTART_DIALOG_PREF_KEY) === "1";
  } catch (_) {
    return false;
  }
}

function saveWindowsSwitchRestartDialogPreference(suppressed) {
  try {
    localStorage.setItem(WINDOWS_SWITCH_RESTART_DIALOG_PREF_KEY, suppressed ? "1" : "0");
  } catch (_) {}
}

function loadDebugCapturePreference() {
  try {
    return localStorage.getItem(DEBUG_CAPTURE_PREF_KEY) === "1";
  } catch (_) {
    return false;
  }
}

function saveDebugCapturePreference(enabled) {
  try {
    localStorage.setItem(DEBUG_CAPTURE_PREF_KEY, enabled ? "1" : "0");
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

function usagePercentNumberFromUsage(usage) {
  const n = Number(usage?.remaining_percent);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n)));
}

function usageErrorLabel(rowError) {
  const msg = String(rowError || "").trim();
  if (!msg) return "";
  const lower = msg.toLowerCase();
  if (lower === "http 401") return "auth expired";
  if (lower === "http 403") return "access denied";
  if (lower.startsWith("http ")) return msg;
  if (isTimeoutErrorMessage(msg)) return "timeout";
  if (lower.includes("missing access_token/account_id")) return "missing auth";
  return msg;
}

function isAuthExpiredLabel(value) {
  return String(value || "").trim().toLowerCase() === "auth expired";
}

function isUsageLoadingState(usage, rowError, rowLoading) {
  if (rowLoading) return true;
  const pct = usagePercentNumberFromUsage(usage);
  if (!rowError) return false;
  const msg = String(rowError || "").toLowerCase();
  let transient = msg.includes("request failed") || isTimeoutErrorMessage(msg);
  if (!transient && msg.startsWith("http ")) {
    const code = Number.parseInt(msg.slice(5).trim(), 10);
    if (Number.isFinite(code)) {
      transient = code >= 500 || code === 408 || code === 429;
    }
  }
  if (!transient) return false;
  if (!Number.isFinite(pct)) return true;
  const resetTs = Number(usage?.resets_at || 0);
  return !(Number.isFinite(resetTs) && resetTs > 0);
}

function formatRemainCell(ts, withSeconds, loading, rowError) {
  if (loading) {
    return ts ? fmtRemain(ts, withSeconds) : "loading...";
  }
  const label = usageErrorLabel(rowError);
  if (label) return label;
  return fmtRemain(ts, withSeconds);
}

function extractEmailFromHint(hint) {
  const left = String(hint || "").split("|")[0].trim();
  return left.includes("@") ? left : "";
}

function buildUsageLoadingSnapshot(prevUsage, listPayload, currentPayload, errorMsg, loadingMode = false) {
  const prevProfiles = Array.isArray(prevUsage?.profiles) ? prevUsage.profiles : [];
  const listProfiles = Array.isArray(listPayload?.profiles) ? listPayload.profiles : [];
  const sourceProfiles = prevProfiles.length ? prevProfiles : listProfiles.map((profile) => ({
    name: profile?.name || "",
    email: extractEmailFromHint(profile?.account_hint),
    account_id: profile?.account_id || "-",
    usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
    usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
    plan_type: null,
    is_paid: null,
    is_current: false,
    same_principal: !!profile?.same_principal,
    error: errorMsg || "request failed",
    saved_at: profile?.saved_at || null,
    auto_switch_eligible: !!profile?.auto_switch_eligible,
  }));

  const currentEmail = currentPayload && !currentPayload.__error
    ? extractEmailFromHint(currentPayload.account_hint)
    : "";

  const profiles = sourceProfiles.map((profile) => {
    const sameCurrent = !!profile.is_current;
    const matchesCurrent = currentEmail
      ? String(profile.email || "").toLowerCase() === currentEmail.toLowerCase()
      : sameCurrent;
    return {
      ...profile,
      usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
      usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
      plan_type: profile.plan_type ?? null,
      is_paid: typeof profile.is_paid === "boolean" ? profile.is_paid : null,
      is_current: !!matchesCurrent,
      error: errorMsg || profile.error || "request failed",
      loading_usage: !!loadingMode,
    };
  });
  const currentProfile = profiles.find((profile) => profile.is_current)?.name || null;
  return { refreshed_at: new Date().toISOString(), current_profile: currentProfile, profiles };
}

function usageMetricSignature(usage) {
  const pct = usagePercentNumberFromUsage(usage);
  const resetTs = Number(usage?.resets_at || 0);
  const text = String(usage?.text || "");
  return `${Number.isFinite(pct) ? pct : "na"}|${Number.isFinite(resetTs) ? resetTs : "na"}|${text}`;
}

function markUsageFlashUpdates(prevUsage, nextUsage, usageFlashUntilRef) {
  if (!prevUsage || !nextUsage || !usageFlashUntilRef) return;
  const prevRows = Array.isArray(prevUsage?.profiles) ? prevUsage.profiles : [];
  const nextRows = Array.isArray(nextUsage?.profiles) ? nextUsage.profiles : [];
  if (!prevRows.length || !nextRows.length) return;
  const until = Date.now() + 1400;
  const prevByName = new Map();
  prevRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (name) prevByName.set(name, row);
  });
  nextRows.forEach((row) => {
    const name = String(row?.name || "").trim();
    if (!name) return;
    const prev = prevByName.get(name);
    if (!prev) return;
    if (usageMetricSignature(prev.usage_5h) !== usageMetricSignature(row.usage_5h)) {
      usageFlashUntilRef[`${name}|h5`] = until;
    }
    if (usageMetricSignature(prev.usage_weekly) !== usageMetricSignature(row.usage_weekly)) {
      usageFlashUntilRef[`${name}|weekly`] = until;
    }
  });
}

function shouldFlashUsage(usageFlashUntilRef, name, metric, loading) {
  if (loading) return false;
  const key = `${String(name || "").trim()}|${metric}`;
  const until = Number(usageFlashUntilRef?.[key] || 0);
  if (!Number.isFinite(until) || until <= 0) return false;
  if (until < Date.now()) {
    delete usageFlashUntilRef[key];
    return false;
  }
  return true;
}

function formatPctValue(value) {
  const percent = clampPercent(value);
  return percent === null ? "-" : `${percent}%`;
}

function progressToneClass(value) {
  const tone = usageTone(value);
  return tone ? `progress-tone-${tone}` : "";
}

function normalizeChainNames(list) {
  if (!Array.isArray(list)) {
    return [];
  }
  const names = [];
  const seen = new Set();
  for (const item of list) {
    const name = String(item || "").trim();
    if (!name || seen.has(name)) {
      continue;
    }
    seen.add(name);
    names.push(name);
  }
  return names;
}

function normalizeChainPayload(payload) {
  const chain = normalizeChainNames(payload?.chain);
  const manualChain = normalizeChainNames(payload?.manual_chain);
  const items = [];
  const seenItems = new Set();
  for (const item of (Array.isArray(payload?.items) ? payload.items : [])) {
    const name = String(item?.name || "").trim();
    if (!name || seenItems.has(name)) {
      continue;
    }
    seenItems.add(name);
    items.push({
      name,
      remaining_5h: clampPercent(item?.remaining_5h),
      remaining_weekly: clampPercent(item?.remaining_weekly),
    });
  }
  const chainText = String(payload?.chain_text || "").trim() || (chain.length ? chain.join(" -> ") : "-");
  return {
    chain,
    manual_chain: manualChain,
    items,
    chain_text: chainText,
  };
}

function ensureLockedChainOrder(list, lockedName = "") {
  const names = normalizeChainNames(list);
  const locked = String(lockedName || "").trim();
  if (!locked) {
    return names;
  }
  const rest = names.filter((name) => name !== locked);
  return [locked, ...rest];
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

function formatAccountDetailValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = String(value).trim();
  return text || "-";
}

function isInteractiveEventTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("button, a, input, select, textarea, label, [data-no-row-open='true']"));
}

function escapeRowKey(value) {
  const text = String(value || "");
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(text);
  }
  return text.replace(/["\\]/g, "\\$&");
}

function captureProfileTableRowRects(root = document) {
  if (!root || typeof root.querySelectorAll !== "function") {
    return {};
  }
  const rects = {};
  const selector =
    typeof root.matches === "function" && root.matches(".profiles-data-table")
      ? "tbody tr[data-row-key]"
      : ".profiles-data-table tbody tr[data-row-key]";
  root.querySelectorAll(selector).forEach((row) => {
    const name = String(row.getAttribute("data-row-key") || "").trim();
    if (!name || typeof row.getBoundingClientRect !== "function") return;
    const rect = row.getBoundingClientRect();
    rects[name] = {
      left: rect.left,
      top: rect.top,
    };
  });
  return rects;
}

function remainToneClass(ts) {
  const tone = remainToneFromResetEpochSeconds(ts);
  if (tone === "danger") return "remain-danger";
  if (tone === "warning") return "remain-warning";
  return "remain-normal";
}

const tableColumnLayout = {
  cur: { colClassName: "col-status", width: "24px" },
  profile: { colClassName: "col-profile", width: "5.5%" },
  email: { colClassName: "col-email", width: "9.5%" },
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

const IMPORT_PLAN_ACTIONS = ["import", "skip", "rename", "overwrite"];

function normalizeImportPlanAction(row) {
  const current = String(row?.action || "").trim().toLowerCase();
  if (IMPORT_PLAN_ACTIONS.includes(current)) {
    return current;
  }
  return String(row?.status || "").trim().toLowerCase() === "ready" ? "import" : "skip";
}

function cloneImportPlanRows(rows) {
  if (!Array.isArray(rows)) {
    return [];
  }
  return rows.map((row) => ({
    ...row,
    action: normalizeImportPlanAction(row),
    rename_to: String(row?.rename_to || ""),
  }));
}

function importStatusVariant(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "ready") return "success";
  if (normalized.includes("conflict")) return "warning";
  return "danger";
}

function buildImportPlanSummary(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const selectedCount = list.filter((row) => normalizeImportPlanAction(row) !== "skip").length;
  const overwriteCount = list.filter((row) => normalizeImportPlanAction(row) === "overwrite").length;
  const invalidRenameCount = list.filter((row) => (
    normalizeImportPlanAction(row) === "rename" && !String(row?.rename_to || "").trim()
  )).length;
  return {
    total: list.length,
    selectedCount,
    overwriteCount,
    invalidRenameCount,
  };
}

function ensureUniqueNames(list) {
  const names = [];
  const seen = new Set();
  for (const item of (Array.isArray(list) ? list : [])) {
    const name = String(item || "").trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  return names;
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

async function readResponseErrorMessage(response, fallbackMessage) {
  try {
    const payload = await response.json();
    const message = String(payload?.error?.message || payload?.message || "").trim();
    if (message) return message;
  } catch (_) {}
  return fallbackMessage;
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
  if (normalized === "debug") return "Debug";
  if (normalized === "warn" || normalized === "warning") return "Warn";
  if (normalized === "error") return "Error";
  return "Info";
}

function isLikelyEmail(value) {
  const text = String(value || "").trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text);
}

function normalizeAuthUrl(candidate) {
  const raw = String(candidate || "").trim().replace(/[),.;]+$/, "");
  if (!raw || isLikelyEmail(raw)) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^auth\.openai\.com\/\S+/i.test(raw)) return `https://${raw}`;
  if (/^auth\.openai\.com$/i.test(raw)) return "https://auth.openai.com/";
  return "";
}

function isCopyableUrl(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  try {
    const parsed = new URL(text);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (_) {
    return false;
  }
}

function resolveSessionLoginUrl(session, mode = "device") {
  const directUrl = normalizeAuthUrl(session?.url);
  if (directUrl) return directUrl;
  const lines = Array.isArray(session?.recent_output) ? session.recent_output : [];
  for (const line of lines) {
    const text = String(line || "").trim();
    if (!text) continue;
    const matchWithProtocol = text.match(/https?:\/\/\S+/i);
    const normalizedWithProtocol = normalizeAuthUrl(matchWithProtocol?.[0] || "");
    if (normalizedWithProtocol) return normalizedWithProtocol;
    const matchAuthHost = text.match(/\bauth\.openai\.com(?:\/\S*)?/i);
    const normalizedAuthHost = normalizeAuthUrl(matchAuthHost?.[0] || "");
    if (normalizedAuthHost) return normalizedAuthHost;
  }
  if (String(mode || "").toLowerCase() === "device") {
    return "https://auth.openai.com/activate";
  }
  return "https://auth.openai.com/";
}

function RemainLoadingIndicator() {
  return <span className="remain-loading-spinner" role="status" aria-label="Loading" />;
}

function AuthExpiredBadge({ className = "" }) {
  return (
    <Badge variant="danger" className={["auth-expired-chip", className].filter(Boolean).join(" ")}>
      auth expired
    </Badge>
  );
}

function LoginModeHelp({ mode = "device" }) {
  const normalized = String(mode || "device").toLowerCase();
  const isDevice = normalized === "device";
  const currentLabel = isDevice ? "Device Login" : "Normal Login";
  return (
    <div className="auth-mode-help">
      <div className="auth-mode-help-head">
        <span className="muted">Mode guidance</span>
        <Badge variant="neutral">Current: {currentLabel}</Badge>
      </div>
      <p className="muted"><strong>Device Login:</strong> Uses URL + code flow. Best for restricted/headless login situations.</p>
      <p className="muted"><strong>Normal Login:</strong> Opens standard interactive browser login. Faster when browser auth is stable.</p>
    </div>
  );
}

function UsageCell({ row, usageKey, flash = false, authExpiredAsUnknown = false }) {
  const usage = row?.[usageKey];
  const loading = isUsageLoadingState(usage, row?.error, row?.loading_usage);
  const errorLabel = usageErrorLabel(row?.error);
  const value = usageValue(row, usageKey);
  const color = usageColor(value);
  const showUnknown = authExpiredAsUnknown && errorLabel === "auth expired";

  if (!loading && errorLabel) {
    const showAuthExpiredChip = isAuthExpiredLabel(errorLabel);
    const displayError = showUnknown && !showAuthExpiredChip ? "?" : errorLabel;
    return (
      <div className="usage-cell" title={showUnknown ? "unknown" : errorLabel}>
        <div className="usage-top">
          {showAuthExpiredChip
            ? <AuthExpiredBadge />
            : <span className="usage-pct usage-low">{displayError}</span>}
        </div>
        <div className="usage-bar-track" aria-hidden="true">
          <div className="usage-bar-fill usage-bar-error" style={{ width: "100%" }} />
        </div>
      </div>
    );
  }

  const label = loading ? "" : value === null ? "-" : `${value}%`;
  return (
    <div className={`usage-cell ${loading ? "usage-cell-loading" : ""} ${flash ? "usage-cell-updated" : ""}`.trim()} title={loading ? "Usage loading" : value === null ? "Usage unavailable" : `${value}% remaining`}>
      <div className="usage-top">
        {loading ? <span className="usage-pct loading-placeholder" aria-hidden="true" /> : (
          <span className={`usage-pct ${value === null ? "loading-text" : ""}`} style={value === null ? undefined : { color }}>
            {label}
          </span>
        )}
      </div>
      <div className={`usage-bar-track ${loading ? "loading" : ""}`} aria-hidden="true">
        <div
          className={`usage-bar-fill ${flash ? "usage-bar-blink" : ""}`.trim()}
          style={loading || value === null ? { width: "0%" } : { width: `${value}%`, background: color }}
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
      </div>
      <div className="sidebar-usage-main">
        <div className="sidebar-usage-track" aria-hidden="true">
          <div
            className="sidebar-usage-fill"
            style={value === null ? { width: "0%" } : { width: `${value}%`, background: color }}
          />
        </div>
        <span className={value === null ? "loading-text sidebar-usage-pct" : "sidebar-usage-pct"} style={value === null ? undefined : { color }}>
          {labelValue}
        </span>
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

const SIDEBAR_APP_VERSION_FALLBACK = "v0.0.21";

function VersionDisplay({ version, updaterDevMode = false, className = "" }) {
  const appVersion = String(version || SIDEBAR_APP_VERSION_FALLBACK).trim() || SIDEBAR_APP_VERSION_FALLBACK;
  return (
    <span className={["version-display", className].filter(Boolean).join(" ")}>
      <span className="version-display-text" title={appVersion}>{appVersion}</span>
      {updaterDevMode ? <span className="sidebar-dev-badge" title="Dev/test updater mode">D</span> : null}
    </span>
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

function Sidebar({ state, activeView, mode, canToggle, onModeChange, onNavigate, updateAvailable, version, updaterDevMode = false, onExit }) {
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
            <span className={`nav-mark ${mode === "minimal" && view.id === "update" && updateAvailable ? "nav-mark-update-alert" : ""}`}><NavIcon id={view.icon} /></span>
            {mode === "fixed" && <span>{view.label}</span>}
            {mode === "fixed" && view.id === "about" ? <VersionDisplay version={version} updaterDevMode={updaterDevMode} className="sidebar-about-version" /> : null}
            {view.id === "update" && updateAvailable && mode !== "minimal" ? <span className="nav-dot" aria-hidden="true" /> : null}
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

const THEME_MODE_LABELS = {
  auto: "Auto",
  light: "Light",
  dark: "Dark",
};

function CurrentThemeIcon({ themeMode }) {
  switch (normalizeThemeMode(themeMode)) {
    case "light":
      return <ThemeLightIcon data-testid="theme-icon-light" />;
    case "dark":
      return <ThemeDarkIcon data-testid="theme-icon-dark" />;
    default:
      return <ThemeAutoIcon data-testid="theme-icon-auto" />;
  }
}

function TopBar({ activeTitle, updateStatus, loading, themeMode, onCycleTheme, onRefresh, onRestart }) {
  const currentThemeMode = normalizeThemeMode(themeMode);
  const nextThemeMode = getNextThemeMode(currentThemeMode);

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
        <Button
          variant="icon"
          className="topbar-theme-btn"
          data-testid="topbar-theme-button"
          aria-label={`Theme mode ${THEME_MODE_LABELS[currentThemeMode]}. Switch to ${THEME_MODE_LABELS[nextThemeMode]}`}
          title={`Theme mode: ${THEME_MODE_LABELS[currentThemeMode]}. Click to switch to ${THEME_MODE_LABELS[nextThemeMode]}.`}
          onClick={onCycleTheme}
        >
          <CurrentThemeIcon themeMode={currentThemeMode} />
        </Button>
      </div>
    </header>
  );
}

function AccountsTable({
  profiles,
  switching,
  activatedProfile,
  switchMotion,
  visibleColumns,
  columnWidthResizeEnabled,
  columnWidthOverrides,
  sort,
  onSort,
  onSwitch,
  onOpenRowActions,
  onOpenAccountDetails,
  onToggleEligibility,
  onColumnResize,
  wideMode,
  compactMode,
  viewportSizeClass,
  shouldFlashUsageFn,
}) {
  const tableRef = useRef(null);
  const lastMotionTokenRef = useRef("");

  useLayoutEffect(() => {
    const motion = switchMotion || {};
    const motionToken = String(motion.token || "");
    if (!motionToken || lastMotionTokenRef.current === motionToken || !tableRef.current) {
      return undefined;
    }
    lastMotionTokenRef.current = motionToken;

    const table = tableRef.current;
    const afterRects = captureProfileTableRowRects(table);
    let plans = buildSwitchRowMotionPlans(motion.fromRects || {}, afterRects);
    if (Array.isArray(motion.affectedNames) && motion.affectedNames.length) {
      const affectedNames = new Set(motion.affectedNames);
      plans = plans.filter((plan) => affectedNames.has(plan.name));
    }
    if (!plans.length) {
      return undefined;
    }

    const animatedRows = [];
    plans.forEach((plan) => {
      const row = table.querySelector(`tbody tr[data-row-key="${escapeRowKey(plan.name)}"]`);
      if (!row) return;
      row.classList.add("switch-row-moving");
      if (plan.name === motion.target) {
        row.classList.add("switch-row-picked");
      }
      row.style.transition = "none";
      row.style.transform = `translate3d(${plan.dx}px, ${plan.dy}px, 0)`;
      row.style.opacity = plan.name === motion.target ? "0.72" : "0.82";
      row.style.zIndex = plan.name === motion.target ? "4" : "2";
      animatedRows.push(row);
    });

    if (!animatedRows.length) {
      return undefined;
    }

    const startAnimation = window.requestAnimationFrame(() => {
      animatedRows.forEach((row) => {
        row.classList.add("switch-row-settling");
        row.style.transition = "";
        row.style.transform = "translate3d(0, 0, 0)";
        row.style.opacity = "1";
      });
    });

    const cleanupTimer = window.setTimeout(() => {
      animatedRows.forEach((row) => {
        row.classList.remove("switch-row-moving", "switch-row-picked", "switch-row-settling");
        row.style.transition = "";
        row.style.transform = "";
        row.style.opacity = "";
        row.style.zIndex = "";
      });
    }, SWITCH_ROW_MOTION_MS + SWITCH_ROW_CLEANUP_BUFFER_MS);

    return () => {
      window.cancelAnimationFrame(startAnimation);
      window.clearTimeout(cleanupTimer);
      animatedRows.forEach((row) => {
        row.classList.remove("switch-row-moving", "switch-row-picked", "switch-row-settling");
        row.style.transition = "";
        row.style.transform = "";
        row.style.opacity = "";
        row.style.zIndex = "";
      });
    };
  }, [switchMotion?.token]);

  const columnTitleByKey = {
    cur: "Status. Active = green dot, Inactive = gray dot.",
    h5: "5h means the five-hour usage window.",
    h5remain: "Remaining time until 5h usage resets.",
    h5reset: "Absolute time when 5h usage resets.",
    weeklyremain: "W means weekly window. Remaining time until weekly reset.",
    weeklyreset: "Absolute time when weekly usage resets.",
  };
  const visibleColumnDefs = columnDefs
    .filter((column) => visibleColumns[column.key] && isColumnVisibleForViewport(column.key, viewportSizeClass));
  const profileColumnWidths = resolveProfileColumnWidths(
    visibleColumnDefs.map((column) => column.key),
    viewportSizeClass,
    columnWidthOverrides,
  );
  const columns = visibleColumnDefs
    .map((column) => ({
      key: column.key,
      label: column.label,
      title: columnTitleByKey[column.key],
      colClassName: tableColumnLayout[column.key]?.colClassName || "",
      width: profileColumnWidths[column.key] || tableColumnLayout[column.key]?.width,
      resizable: columnWidthResizeEnabled && isProfileColumnResizable(column.key),
      resizeMinWidth: getProfileColumnResizeBounds(column.key).min,
      resizeMaxWidth: getProfileColumnResizeBounds(column.key).max,
      className: ["email", "id", "added", "note", "h5remain", "h5reset", "weeklyremain", "weeklyreset"].includes(column.key)
        ? `${column.key === "email" ? "email-cell" : ""} ${column.key === "id" ? "id-cell" : ""} ${column.key === "added" ? "added-cell" : ""} ${column.key === "note" ? "note-cell" : ""} ${column.key === "h5remain" || column.key === "h5reset" || column.key === "weeklyremain" || column.key === "weeklyreset" ? "reset-cell" : ""}`.trim()
        : "",
      sortable: true,
      render: (profile) => {
        const quotaBlocked = (usageValue(profile, "usage_5h") ?? 1) <= 0 || (usageValue(profile, "usage_weekly") ?? 1) <= 0;
        const disableSwitch = profile.is_current || Boolean(switching);
        const isSwitchingProfile = switching === profile.name;
        const noteText = String(profile.note || (profile.same_principal ? "same-principal" : "")).trim();
        const h5Loading = isUsageLoadingState(profile.usage_5h, profile.error, profile.loading_usage);
        const wLoading = isUsageLoadingState(profile.usage_weekly, profile.error, profile.loading_usage);
        const rowErrorLabel = usageErrorLabel(profile.error);
        const h5Flash = shouldFlashUsageFn?.(profile.name, "h5", h5Loading) || false;
        const wFlash = shouldFlashUsageFn?.(profile.name, "weekly", wLoading) || false;
        switch (column.key) {
          case "cur":
            return <StatusDot active={profile.is_current} />;
          case "profile":
            return <strong className="profile-name">{profile.name}</strong>;
          case "email":
            return <span className="muted" title={profile.email_display}>{profile.email_display}</span>;
            case "h5":
            return <UsageCell row={profile} usageKey="usage_5h" flash={h5Flash} authExpiredAsUnknown />;
          case "h5remain":
            if (h5Loading) {
              return <RemainLoadingIndicator />;
            }
            {
              const remainText = formatRemainCell(profile.usage_5h?.resets_at, true, false, profile.error);
              const remainIsError = Boolean(rowErrorLabel);
              const remainDisplay = isAuthExpiredLabel(remainText) ? "" : remainText;
              return (
                <span className={`remain-value ${remainIsError ? "loading-text" : ""}`.trim()} title={fmtResetFull(profile.usage_5h?.resets_at)}>
                  {remainDisplay}
                </span>
              );
            }
          case "h5reset":
            if (rowErrorLabel) {
              return <span className="muted" />;
            }
            return <span className="muted" title={fmtResetFull(profile.usage_5h?.resets_at)}>{fmtReset(profile.usage_5h?.resets_at)}</span>;
            case "weekly":
            return <UsageCell row={profile} usageKey="usage_weekly" flash={wFlash} authExpiredAsUnknown />;
            case "weeklyremain":
              if (wLoading) {
                return <RemainLoadingIndicator />;
              }
              {
                const remainText = formatRemainCell(profile.usage_weekly?.resets_at, false, false, profile.error);
                const remainIsError = Boolean(rowErrorLabel);
                const remainDisplay = isAuthExpiredLabel(remainText) ? "" : remainText;
                return (
                  <span className={`remain-value ${remainIsError ? "loading-text" : ""}`.trim()} title={fmtResetFull(profile.usage_weekly?.resets_at)}>
                    {remainDisplay}
                  </span>
                );
              }
          case "weeklyreset":
            if (rowErrorLabel) {
              return <span className="muted" />;
            }
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
            return (
              <span className="muted" title={noteText || "-"}>
                {noteText ? truncateNote(noteText) : ""}
              </span>
            );
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
                      className={`actions-menu-btn actions-switch-btn ${disableSwitch ? "btn-disabled" : ""} ${isSwitchingProfile ? "switch-loading-btn" : ""}`}
                      loading={isSwitchingProfile}
                      disabled={disableSwitch}
                      onClick={() => onSwitch(profile.name)}
                      aria-label={`Switch to ${profile.name}`}
                      title={isSwitchingProfile ? `Switching to ${profile.name}` : `Switch to ${profile.name}`}
                    >
                      {isSwitchingProfile ? <span className="visually-hidden">Switching</span> : "⇄"}
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
                      className={`${disableSwitch ? "btn-disabled" : ""} ${isSwitchingProfile ? "switch-loading-btn" : ""}`.trim()}
                      loading={isSwitchingProfile}
                      disabled={disableSwitch}
                      onClick={() => onSwitch(profile.name)}
                      aria-label={isSwitchingProfile ? `Switching to ${profile.name}` : `Switch to ${profile.name}`}
                      title={isSwitchingProfile ? `Switching to ${profile.name}` : `Switch to ${profile.name}`}
                    >
                      {isSwitchingProfile ? <span className="visually-hidden">Switching</span> : "Switch"}
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
      tableRef={tableRef}
      columns={columns}
      sort={sort}
      onSort={onSort}
      onColumnResize={onColumnResize}
      rows={profiles}
      rowKey={(profile) => profile.name}
      rowClassName={(profile) => buildProfileRowClassName({
        isCurrent: profile.is_current,
        isPending: switching === profile.name,
        isActivated: activatedProfile === profile.name,
      })}
      onRowClick={onOpenAccountDetails}
      rowAriaLabel={(profile) => `Open full details for ${profile?.name || "account"}`}
      emptyState="No profiles available."
    />
  );
}

function AccountsMobileList({ profiles, switching, onSwitch, onOpenRowActions, onOpenAccountDetails }) {
  return (
    <div className="mobile-list" data-testid="profiles-mobile-list">
      {profiles.map((profile) => {
        const h5Value = usageValue(profile, "usage_5h");
        const weeklyValue = usageValue(profile, "usage_weekly");
        const rowErrorLabel = usageErrorLabel(profile.error);
        const quotaBlocked = (h5Value ?? 1) <= 0 || (weeklyValue ?? 1) <= 0;
        const switchDisabled = profile.is_current || Boolean(switching);
        const isSwitchingProfile = switching === profile.name;
        const h5Tone = usageTone(h5Value);
        const weeklyTone = usageTone(weeklyValue);

        return (
          <div
            key={profile.name}
            className="mobile-row row-clickable"
            role="button"
            tabIndex={0}
            aria-label={`Open full details for ${profile.name || "account"}`}
            onClick={(event) => {
              if (isInteractiveEventTarget(event.target)) return;
              onOpenAccountDetails(profile);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onOpenAccountDetails(profile);
            }}
          >
            <div className="mobile-head">
              <div className="mobile-left">
                <StatusDot active={profile.is_current} />
                <span className="mobile-profile">{profile.name || "-"}</span>
              </div>
              <div className="mobile-actions">
                <Button
                  variant={quotaBlocked ? "danger" : "primary"}
                  className={`${switchDisabled ? "btn-disabled" : ""} ${isSwitchingProfile ? "switch-loading-btn" : ""}`.trim()}
                  loading={isSwitchingProfile}
                  disabled={switchDisabled}
                  onClick={() => onSwitch(profile.name)}
                  aria-label={isSwitchingProfile ? `Switching to ${profile.name}` : `Switch to ${profile.name}`}
                  title={isSwitchingProfile ? `Switching to ${profile.name}` : `Switch to ${profile.name}`}
                >
                  {isSwitchingProfile ? <span className="visually-hidden">Switching</span> : "Switch"}
                </Button>
                <Button className="actions-menu-btn" data-mobile-row-actions={profile.name} onClick={() => onOpenRowActions(profile)}>⋯</Button>
              </div>
            </div>
            <div className="mobile-email">{profile.email_display}</div>
            {isAuthExpiredLabel(rowErrorLabel) ? (
              <div className="mobile-auth-warning">
                <AuthExpiredBadge />
              </div>
            ) : null}
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
  switchMotion,
  profileDeckOrder,
  onSwitch,
  onAddAccount,
  onImportProfiles,
  onExportProfiles,
  onRemoveAll,
  onOpenColumns,
  onOpenRowActions,
  onOpenAccountDetails,
  onToggleEligibility,
  visibleColumns,
  columnWidthResizeEnabled,
  columnWidthOverrides,
  sort,
  onSort,
  onColumnResize,
  compactMode,
  viewportSizeClass,
  shouldFlashUsageFn,
}) {
  const sortedProfiles = sortRows(buildProfileRows(state), sort);
  const profiles = buildRowsByNameOrder(sortedProfiles, profileDeckOrder);
  const visibleColumnCount = Object.values(visibleColumns || {}).filter(Boolean).length;
  const wideMode = visibleColumnCount > 8;
  const activeColumnCount = columnDefs.filter((column) => visibleColumns?.[column.key]).length;
  const totalColumnCount = columnDefs.length;

  return (
    <section className="view profiles-view" data-testid="profiles-view">
      <div className="profiles-view-shell">
        <div className="accounts-toolbar">
          <div className="accounts-actions accounts-actions-left">
            <Button onClick={onImportProfiles}>Import</Button>
            <Button className="profiles-export-btn" onClick={onExportProfiles}>
              <span className="btn-label">Export</span>
            </Button>
          </div>
          <div className="accounts-actions">
            <Button variant="primary" onClick={onAddAccount}>Add Account</Button>
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
      <div className={`table-wrap profiles-table-wrap scrollable ${wideMode ? "wide-columns" : ""}`}>
          <AccountsTable
            profiles={profiles}
            switching={switching}
            activatedProfile={activatedProfile}
            switchMotion={switchMotion}
            visibleColumns={visibleColumns}
            columnWidthResizeEnabled={columnWidthResizeEnabled}
            columnWidthOverrides={columnWidthOverrides}
            wideMode={wideMode}
            compactMode={compactMode}
            viewportSizeClass={viewportSizeClass}
            shouldFlashUsageFn={shouldFlashUsageFn}
            sort={sort}
            onSort={onSort}
            onColumnResize={onColumnResize}
            onSwitch={onSwitch}
            onOpenRowActions={onOpenRowActions}
            onOpenAccountDetails={onOpenAccountDetails}
            onToggleEligibility={onToggleEligibility}
          />
          <AccountsMobileList
            profiles={profiles}
            switching={switching}
            onSwitch={onSwitch}
            onOpenRowActions={onOpenRowActions}
            onOpenAccountDetails={onOpenAccountDetails}
          />
        </div>
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

  return formatAutoSwitchCountdown(dueAtText, dueAt, now);
}

function AutoSwitchView({ state, autoChain, onSavePatch, onOpenChainEdit, onRunSwitch, onRapidTest, onStopTests, onStopSwitch, onTestAutoSwitch, onAutoArrange, autoArrangeBusy = false }) {
  const autoState = state?.autoSwitch || {};
  const autoConfig = state?.config?.auto_switch || {};
  const countdownText = useCountdownText(autoState.pending_switch_due_at_text, autoState.pending_switch_due_at);
  const chainPayload = normalizeChainPayload(autoChain);
  const profileRows = buildProfileRows(state);
  const profileRowsByName = new Map(profileRows.map((row) => [row.name, row]));
  const chainItemsByName = new Map(chainPayload.items.map((item) => [item.name, item]));
  const chainNames = normalizeChainNames([
    ...chainPayload.chain,
    ...chainPayload.manual_chain,
    ...chainPayload.items.map((item) => item.name),
  ]);
  const orderedChainNames = chainNames.length ? chainNames : normalizeChainNames(profileRows.map((row) => row.name));
  const chainRows = orderedChainNames.map((name) => {
    const profileRow = profileRowsByName.get(name);
    const chainItem = chainItemsByName.get(name);
    const usage5 = clampPercent(chainItem?.remaining_5h);
    const usageWeekly = clampPercent(chainItem?.remaining_weekly);
    return {
      name,
      usage_5h: usage5 === null ? usageValue(profileRow, "usage_5h") : usage5,
      usage_weekly: usageWeekly === null ? usageValue(profileRow, "usage_weekly") : usageWeekly,
    };
  });
  const chainCount = chainRows.length;
  const pendingSwitch = Boolean(autoState.pending_switch_due_at);

  return (
    <section className="view autoswitch-view" data-testid="autoswitch-view">
      <div className="settings-layout autoswitch-layout">
        <div className="settings-card-stack settings-card-stack-main autoswitch-card-stack">
          <SettingsCardShell
            title="Auto-switch rules"
            description="Configure execution timing and run controls for automatic profile switching."
            className={`autoswitch-card-execution auto-switch-card ${pendingSwitch ? "armed" : ""}`}
            testId="autoswitch-card-execution"
            footer={(
              <div className="settings-action-group autoswitch-action-group">
                <ConfirmAction
                  label="Run switch"
                  confirmLabel="Confirm run switch ✓"
                  tone="primary"
                  onConfirm={onRunSwitch}
                />
                <Button onClick={onRapidTest}>Rapid test</Button>
                <Button variant="dangerOutline" onClick={onStopTests}>Stop tests</Button>
                <Button variant="dangerOutline" onClick={onStopSwitch} disabled={!pendingSwitch}>Stop switch</Button>
                <Button onClick={onTestAutoSwitch}>Test auto switch</Button>
              </div>
            )}
          >
            <div className="auto-switch-head">
              <div className="k">Pending switch</div>
              <div className={`auto-switch-countdown ${pendingSwitch ? "active pending" : "active idle"}`}>{countdownText}</div>
            </div>

            <div className="settings-subsection-stack">
              <div className="rules-grid autoswitch-rules-grid">
                <SettingsSubsection title="Execution">
                  <div className="setting-row">
                    <SettingCopy label="Enabled" title="Turn automatic account switching on or off." />
                    <div className="setting-control">
                      <ToggleSwitch
                        checked={!!autoConfig.enabled}
                        onChange={(nextValue) => onSavePatch({ auto_switch: { enabled: nextValue } })}
                        ariaLabel="Enable auto switch"
                      />
                    </div>
                  </div>
                  <div className="setting-row">
                    <SettingCopy label="Delay (seconds)" title="Wait before executing the next switch operation." />
                    <div className="setting-control">
                      <StepperInput
                        value={autoConfig.delay_sec ?? 60}
                        min={0}
                        max={3600}
                        onChange={(value) => onSavePatch({ auto_switch: { delay_sec: value } })}
                      />
                    </div>
                  </div>
                  <div className="setting-row">
                    <SettingCopy label="Switch in flight" title="Shows the target account when a switch job is running." />
                    <div className="setting-current-value">{autoState.switch_in_flight ? autoState.switch_target || "Running" : "No"}</div>
                  </div>
                  <div className="setting-row">
                    <SettingCopy label="Pending switch" title="Live countdown until the next queued switch." />
                    <div className={`setting-current-value ${pendingSwitch ? "pending" : ""}`}>{countdownText}</div>
                  </div>
                </SettingsSubsection>

                <SettingsSubsection title="Selection policy">
                  <div className="setting-row setting-row-top">
                    <SettingCopy label="Ranking mode" title="Define how accounts are ranked for the next switch." />
                    <div className="setting-control settings-select-control">
                      <select value={autoConfig.ranking_mode || "balanced"} onChange={(event) => onSavePatch({ auto_switch: { ranking_mode: event.target.value } })}>
                        <option value="balanced">balanced</option>
                        <option value="max_5h">max_5h</option>
                        <option value="max_weekly">max_weekly</option>
                        <option value="manual">manual</option>
                      </select>
                    </div>
                  </div>
                  <div className="metric-pair-grid">
                    <div className="setting-row">
                      <SettingCopy label="5h switch (%)" title="Switch when five-hour usage reaches this threshold." />
                      <div className="setting-control">
                        <StepperInput
                          value={autoConfig.thresholds?.h5_switch_pct ?? 20}
                          min={0}
                          max={100}
                          onChange={(value) => onSavePatch({ auto_switch: { thresholds: { h5_switch_pct: value } } })}
                        />
                      </div>
                    </div>
                    <div className="setting-row">
                      <SettingCopy label="Weekly switch (%)" title="Switch when weekly usage reaches this threshold." />
                      <div className="setting-control">
                        <StepperInput
                          value={autoConfig.thresholds?.weekly_switch_pct ?? 20}
                          min={0}
                          max={100}
                          onChange={(value) => onSavePatch({ auto_switch: { thresholds: { weekly_switch_pct: value } } })}
                        />
                      </div>
                    </div>
                  </div>
                </SettingsSubsection>
              </div>
            </div>
          </SettingsCardShell>

          <SettingsCardShell
            title="Switch chain"
            description="Inspect the current chain order used by the auto-switch engine."
            className="autoswitch-card-chain auto-switch-card"
            testId="autoswitch-card-chain"
          >
            <div className="settings-subsection-stack">
              <SettingsSubsection
                title="Chain preview"
                meta={`${chainCount} account${chainCount === 1 ? "" : "s"}`}
              >
                <div className="chain-track-wrap">
                  <div className="chain-track">
                    {chainRows.length ? chainRows.map((row, index) => (
                      <React.Fragment key={row.name}>
                        <span className="chain-node">
                          <span className="chain-name">{row.name}</span>
                          <span className={["chain-metric", progressToneClass(row.usage_5h)].filter(Boolean).join(" ")} title="5-hour usage">
                            5H {formatPctValue(row.usage_5h)}
                          </span>
                          <span className={["chain-metric", progressToneClass(row.usage_weekly)].filter(Boolean).join(" ")} title="Weekly usage">
                            W {formatPctValue(row.usage_weekly)}
                          </span>
                        </span>
                        {index < chainRows.length - 1 ? (
                          <span className="chain-arrow" aria-hidden="true">
                            <ArrowRightIcon />
                          </span>
                        ) : null}
                      </React.Fragment>
                    )) : <span className="muted">No profiles available.</span>}
                  </div>
                </div>
                <div className="chain-key">
                  <span title="5H means five-hour usage window">5H = 5-hour usage</span>
                  {" · "}
                  <span title="W means weekly usage window">W = weekly usage</span>
                </div>
                <div className="settings-inline-actions autoswitch-chain-actions">
                  <Button
                    variant="primary"
                    loading={autoArrangeBusy}
                    disabled={autoArrangeBusy}
                    onClick={onAutoArrange}
                    title="Automatically reorder the switch chain based on current ranking policy."
                  >
                    Auto Arrange
                  </Button>
                  <Button onClick={onOpenChainEdit}>Edit</Button>
                </div>
              </SettingsSubsection>
            </div>
          </SettingsCardShell>
        </div>
      </div>
    </section>
  );
}

function GuideView({ isMacDesktop = false }) {
  const modifier = shortcutModifierLabel(isMacDesktop);
  const quitKeys = [`${modifier}+Q`, ...(isMacDesktop ? [] : ["Alt+F4"])];
  const shortcuts = [
    ...views.map((view) => ({
      id: `nav-${view.id}`,
      label: view.label,
      keys: [`${modifier}+${view.id === "guide" ? "/" : view.key.toUpperCase()}`],
    })),
    { id: "next", label: "Switch to next section", keys: [`${modifier}+PageDown`] },
    { id: "previous", label: "Switch to previous section", keys: [`${modifier}+PageUp`] },
    { id: "refresh-primary", label: "Refresh profiles table", keys: [`${modifier}+R`, "F5"] },
    { id: "zoom-in", label: "Zoom in", keys: [`${modifier}+=`] },
    { id: "zoom-out", label: "Zoom out", keys: [`${modifier}+-`] },
    { id: "zoom-reset", label: "Zoom reset", keys: [`${modifier}+0`] },
    { id: "toggle-sidebar", label: "Toggle sidebar", keys: [`${modifier}+B`] },
    { id: "quit", label: "Quit app", keys: quitKeys },
    { id: "quit-stop-core", label: "Quit + stop core", keys: [`${modifier}+Shift+Q`] },
  ];

  return (
    <section className="view guide-view">
      <div className="guide-layout">
        <div className="guide-quick">
          <SectionCard className="settings-card guide-quick-card">
            <div className="group-title">Quick start</div>
            <p className="muted">Use Add Account, Switch, Import, Export, and Auto Switch from the desktop shell.</p>
            <div className="guide-layer-map">
              <LabelValueRow label="Python core" value="Profile storage, switching, usage fetch, and local /api endpoints." />
              <LabelValueRow label="Web UI" value="Stable browser panel with complete local controls and release guidance." />
              <LabelValueRow label="Electron UI" value="Desktop shell, tray/menu integration, runtime setup, and windowed workflow." />
            </div>
          </SectionCard>

          <SectionCard className="settings-card guide-shortcuts-card">
            <div className="group-title">Key shortcuts</div>
            <div className="guide-shortcuts-table">
              {shortcuts.map((item) => (
                <div key={item.id} className="guide-shortcuts-row">
                  <span className="muted">{item.label}</span>
                  <div className="guide-shortcuts-keys">
                    {item.keys.map((keyLabel) => (
                      <code key={`${item.id}-${keyLabel}`}>{keyLabel}</code>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
        <div className="guide-reference">
          <SectionCard className="settings-card guide-reference-card">
            <div className="group-title">Guide map</div>
            <p className="muted guide-reference-copy">
              This view explains how the Python core, web panel, and desktop shell work together so you can choose the right control surface per task.
            </p>
            <details className="guide-topic" open>
              <summary>Python core and CLI contract</summary>
              <ul className="guide-list">
                <li>The Python core is the source of truth for profiles, switching, usage collection, notifications, and auto-switch state.</li>
                <li>CLI-first workflows remain available through commands like <code>save</code>, <code>switch</code>, <code>usage-local</code>, <code>ui</code>, and <code>ui-service</code>.</li>
                <li>Electron and web both consume the same local API contract, so profile data and status stay consistent across surfaces.</li>
              </ul>
            </details>
            <details className="guide-topic" open>
              <summary>Web UI parity and shared behavior</summary>
              <ul className="guide-list">
                <li>Profiles, Auto Switch, notifications thresholds, import/export flows, release notes, and update actions mirror the web panel behavior.</li>
                <li>Current and all-account refresh timers follow the same config values and safe usage refresh model.</li>
                <li>Switching updates active auth through the same backend path used by <code>codex-account switch</code>.</li>
              </ul>
            </details>
            <details className="guide-topic">
              <summary>Electron-only desktop features</summary>
              <ul className="guide-list">
                <li>Runtime setup screen can bootstrap Python/core requirements and show actionable diagnostics before the app opens fully.</li>
                <li>Desktop tray/menu-bar state reflects current usage and offers quick actions like open, refresh, and test notification.</li>
                <li>Native desktop notifications can focus the app window; Windows also supports taskbar usage badge and mini live meter.</li>
              </ul>
            </details>
            <details className="guide-topic">
              <summary>Practical workflows</summary>
              <ul className="guide-list">
                <li>Add a profile with Device Login or Normal Login, then run Switch from table rows to activate it.</li>
                <li>Use Import/Export for migration archives and review import analysis before apply actions.</li>
                <li>Tune Auto Switch delay, thresholds, ranking mode, and chain order, then use Test, Rapid Test, or Run Switch based on the scenario.</li>
                <li>Use the Update page for release checks and guided upgrade flow while keeping the desktop shell open.</li>
              </ul>
            </details>
            <details className="guide-topic">
              <summary>Troubleshooting and safety</summary>
              <ul className="guide-list">
                <li>Open Debug view to inspect runtime/API logs and export a JSON snapshot for issue reports.</li>
                <li>If usage shows auth expired for a profile, refresh that account with a new healthy login session.</li>
                <li>Current client support targets Codex CLI and Codex VS Code extension; some client launch paths still need manual reload after switch.</li>
              </ul>
            </details>
          </SectionCard>
        </div>
      </div>
    </section>
  );
}

function UpdateView({
  releaseNotes,
  updateStatus,
  currentVersion,
  updaterDevMode = false,
  checking,
  updating,
  systemPythonSelection = "skip",
  onCheck,
  onRunUpdate,
  onRefreshReleaseNotes,
  onSystemPythonSelectionChange,
}) {
  const notes = Array.isArray(releaseNotes?.releases) ? releaseNotes.releases : [];
  const updateAvailable = !!updateStatus?.update_available;
  const systemPython = updateStatus?.system_python || {};
  const updateTone = updateStatus?.desktop_update_needed
    || updateStatus?.core_update_needed
    || systemPython.required
    ? "danger"
    : systemPython.optional
      ? "warning"
      : "good";
  const currentTone = updateAvailable ? "danger" : "good";
  const desktopAppTone = updateStatus?.desktop_update_needed ? "danger" : "good";
  const coreTone = updateStatus?.core_update_needed ? "danger" : "good";
  const systemPythonTone = systemPython.required ? "danger" : (systemPython.optional ? "warning" : "good");
  const compactStatusSummary = systemPython.required
    ? "Python required"
    : updateStatus?.desktop_update_needed
      ? "Desktop update"
      : updateStatus?.core_update_needed
        ? "Core sync"
        : systemPython.optional
          ? "Optional Python"
          : "Up to date";
  const systemPythonSummary = systemPython.required
    ? "Required before Python core sync can finish."
    : systemPython.optional
      ? `Optional update to Python ${systemPython.recommended_version || "latest supported"}`
      : systemPython.supported
        ? `Detected Python ${systemPython.version || "supported"}`
        : "Not detected";

  return (
    <section className="view update-view">
      <div className="sparse-page-layout">
        <SectionCard className="settings-card update-panel update-status-card">
          <div className="group-title">Update status</div>
          <div className="update-status-summary">
            <div className={`update-status-pill tone-${currentTone}`}>
              <span className="update-status-pill-label">Current</span>
              <VersionDisplay version={currentVersion || "-"} updaterDevMode={updaterDevMode} />
            </div>
            <div className="update-status-pill">
              <span className="update-status-pill-label">Latest</span>
              <span>{updateStatus?.latest_version || "-"}</span>
            </div>
            <div className={`update-status-pill strong tone-${updateTone}`}>
              <span className="update-status-pill-label">Status</span>
              <span>{compactStatusSummary}</span>
            </div>
          </div>
          <div className="update-source-row">
            <div className="update-status-pill update-source-pill">
              <span className="update-status-pill-label">Source</span>
              <span>{updateStatus?.status_text || updateStatus?.status || "Unknown"}</span>
            </div>
          </div>
          <div className="update-layer-grid">
            <div className={`update-layer-item tone-${desktopAppTone}`}>
              <span className="update-layer-item-label">Desktop app</span>
              <span className="update-layer-item-value">{updateStatus?.desktop_update_needed ? `Update ${updateStatus?.latest_version || "available"}` : "Current build installed"}</span>
            </div>
            <div className={`update-layer-item tone-${coreTone}`}>
              <span className="update-layer-item-label">Python core</span>
              <span className="update-layer-item-value">{updateStatus?.core_update_needed ? `Sync to ${updateStatus?.target_version || updateStatus?.current_version || "current build"}` : `Core ${updateStatus?.core_version || "-"}`}</span>
            </div>
            <div className={`update-layer-item tone-${systemPythonTone} ${systemPython.required ? "required" : ""}`}>
              <span className="update-layer-item-label">System Python</span>
              <span className="update-layer-item-value">{systemPythonSummary}</span>
            </div>
          </div>
          {systemPython.optional ? (
            <label className="update-optional-toggle" data-no-row-open="true">
              <input
                type="checkbox"
                checked={systemPythonSelection === "update"}
                onChange={(event) => onSystemPythonSelectionChange?.(event.target.checked ? "update" : "skip")}
              />
              <span>Update System Python too{systemPython.recommended_version ? ` (${systemPython.recommended_version})` : ""}</span>
            </label>
          ) : null}
          {systemPython.required ? (
            <div className="workspace-error-inline">
              System Python 3.11+ is required before the Python core update can finish.
              {!systemPython.auto_update_supported ? " This platform uses a manual installer handoff." : ""}
            </div>
          ) : null}
          {checking ? <div className="update-inline-loading" role="status" aria-live="polite">Checking for updates…</div> : null}
          <div className="settings-inline-actions">
            <Button loading={checking} onClick={onCheck} disabled={checking}>Check for updates</Button>
            <Button variant={updateAvailable ? "primary" : "secondary"} loading={updating} onClick={onRunUpdate} disabled={!updateAvailable || checking || updating}>
              {updating ? "Updating" : "Update now"}
            </Button>
          </div>
        </SectionCard>
        <SectionCard className="settings-card guide-changelog-card sparse-bottom-fill update-changelog-card">
          <div className="group-title">Changelog</div>
          <div className="settings-inline-actions">
            <Button onClick={onRefreshReleaseNotes}>Reload release notes</Button>
          </div>
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

function UpdateProgressDialog({ modal, onClose, onRetry }) {
  const progressPercent = Number.isFinite(Number(modal?.percent)) ? Math.max(0, Math.min(100, Math.round(Number(modal.percent)))) : 5;
  const progressWidthClass = `progress-width-${progressPercent}`;
  const progressTone = modal?.status === "failed" ? "danger" : (modal?.status === "running" ? "active" : "default");
  const progressLabel = modal?.status === "failed"
    ? "Update failed"
    : modal?.status === "awaiting-user"
      ? "Waiting for install"
      : modal?.status === "done"
        ? "Update complete"
        : `${progressPercent}% complete`;
  const logs = Array.isArray(modal?.logs) ? modal.logs : [];
  const isInstallerHandoff = modal?.phase === "awaiting_installer" && modal?.status === "awaiting-user";
  const detailClassName = `update-progress-detail${isInstallerHandoff ? " update-progress-detail-warning" : ""}`;

  return (
    <Dialog
      title="Update progress"
      size="md"
      onClose={modal?.dismissible ? onClose : undefined}
      footer={(
        <>
          {modal?.status === "failed" ? <Button onClick={onRetry}>Retry</Button> : null}
          <Button variant="primary" onClick={onClose} disabled={!modal?.dismissible}>
            {modal?.status === "awaiting-user" ? "Done" : "Close"}
          </Button>
        </>
      )}
    >
      <div className="update-progress-dialog">
        <section className="runtime-progress" aria-label="Update progress">
          <div className="runtime-progress-head">
            <strong>{modal?.label || "Preparing update"}</strong>
            <span>{progressLabel}</span>
          </div>
          <div className={`runtime-progress-bar ${progressTone}`} aria-hidden="true">
            <span className={progressWidthClass} />
          </div>
        </section>
        {modal?.detail ? <p className={detailClassName}>{modal.detail}</p> : null}
        {modal?.targetVersion ? (
          <div className="update-progress-meta">
            <LabelValueRow label="Target version" value={modal.targetVersion} />
          </div>
        ) : null}
        {modal?.error ? <div className="workspace-error-inline">{modal.error}</div> : null}
        <div className="update-progress-log" aria-label="Update steps">
          {logs.length ? logs.slice(-10).map((entry, index) => (
            <div key={`${entry.ts || index}-${entry.label || entry.phase || "step"}`} className="update-progress-log-row">
              <strong>{entry.label || entry.phase || "Step"}</strong>
              <span>{entry.detail || entry.message || entry.error || entry.status || "-"}</span>
            </div>
          )) : <div className="muted">No update steps recorded yet.</div>}
        </div>
      </div>
    </Dialog>
  );
}

function DebugView({ debugLogs, captureEnabled, onStartCapture, onStopCapture, onClear, onExport }) {
  const [levelFilter, setLevelFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true);
  const [showJump, setShowJump] = useState(false);
  const panelRef = useRef(null);
  const autoScrollInternalRef = useRef(false);

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
    if (autoScrollEnabled) {
      autoScrollInternalRef.current = true;
      panel.scrollTop = panel.scrollHeight;
      setShowJump(false);
      requestAnimationFrame(() => {
        autoScrollInternalRef.current = false;
      });
    }
  }, [filteredLogs, autoScrollEnabled, captureEnabled]);

  function onPanelScroll(event) {
    const panel = event.currentTarget;
    const distanceFromBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight;
    const nearBottom = distanceFromBottom <= 140;
    if (autoScrollInternalRef.current) {
      setShowJump(!nearBottom);
      return;
    }
    if (autoScrollEnabled && !nearBottom) {
      setAutoScrollEnabled(false);
    }
    setShowJump(!nearBottom);
  }

  function jumpToLatest() {
    const panel = panelRef.current;
    if (!panel) return;
    autoScrollInternalRef.current = true;
    panel.scrollTop = panel.scrollHeight;
    setShowJump(false);
    requestAnimationFrame(() => {
      autoScrollInternalRef.current = false;
    });
  }

  function handleAutoScrollToggle(next) {
    setAutoScrollEnabled(Boolean(next));
    if (next) {
      jumpToLatest();
    }
  }

  return (
    <section className="view debug-view">
      <div className="settings-inline-actions debug-actions debug-actions-right">
        <Button
          variant={captureEnabled ? "danger" : "primary"}
          onClick={captureEnabled ? onStopCapture : onStartCapture}
        >
          {captureEnabled ? "Stop logs" : "Start logs"}
        </Button>
        <Button onClick={onClear}>Clear logs</Button>
        <Button onClick={onExport}>Export debug logs</Button>
      </div>
      <div className="debug-toolbar">
        <div className="debug-filter-chips" role="tablist" aria-label="Log level filter">
          {[
            { key: "all", label: "All" },
            { key: "info", label: "Info" },
            { key: "debug", label: "Debug" },
            { key: "warn", label: "Warn" },
            { key: "error", label: "Error" },
          ].map((item) => (
            <Button
              key={item.key}
              type="button"
              className={`debug-chip debug-chip-${item.key} ${levelFilter === item.key ? "active" : ""}`}
              onClick={() => setLevelFilter(item.key)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <div className="debug-toolbar-controls">
          <span className="muted">Auto-scroll</span>
          <ToggleSwitch
            checked={autoScrollEnabled}
            onChange={handleAutoScrollToggle}
            ariaLabel="Toggle debug log auto-scroll"
            title={autoScrollEnabled ? "Auto-scroll enabled" : "Auto-scroll disabled"}
          />
        </div>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search logs"
          aria-label="Search logs"
        />
      </div>
      <div className="debug-log-panel-wrap">
        <div ref={panelRef} className="debug-log-panel scrollable" onScroll={onPanelScroll}>
          {!captureEnabled ? (
            <div className="muted">Log capture is stopped. Click Start logs to begin collecting entries.</div>
          ) : filteredLogs.length ? filteredLogs.map((row, index) => (
            <div key={`${row.ts || index}-${index}`} className={`debug-line log-${String(row.level || "info").toLowerCase()}`}>
              <span className="debug-ts">{row.ts || "-"}</span>
              <strong className="debug-level">{formatLogLevel(row.level)}</strong>
              <span className="debug-source">{String(row?.source || "app")}</span>
              <span className="debug-message">{row.message || ""}</span>
            </div>
          )) : <div className="muted">No logs yet.</div>}
        </div>
        {showJump && !autoScrollEnabled ? (
          <Button type="button" className="debug-jump-latest" onClick={jumpToLatest}>
            Jump to latest
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function AboutView({ backendState, state, version, updaterDevMode = false, onOpenExternal }) {
  const backendUrl = String(backendState?.baseUrl || "http://127.0.0.1:4673/").trim();
  const projectUrl = "https://github.com/alisinaee/Codex-Account-Manager";
  const authorGithubUrl = "https://github.com/alisinaee";
  const authorLinkedinUrl = "https://www.linkedin.com/in/alisinaee/";
  const ui = state?.config?.ui || {};
  const platformName = window.codexAccountDesktop?.platform || navigator.platform || "unknown";

  return (
    <section className="view about-view" data-testid="about-view">
      <div className="settings-layout about-layout">
        <div className="settings-card-stack settings-card-stack-main about-card-stack">
          <SettingsCardShell
            title="About"
            description="Desktop account switching and usage monitoring for Codex profiles."
            className="about-merged-card"
            testId="about-merged-card"
          >
            <div className="about-merged-content">
              <header className="about-identity">
                <img src={iconUrl} alt="" />
                <div>
                  <h2>Codex Account Manager</h2>
                  <p>Electron desktop shell with Python API backend.</p>
                  <span>Version <VersionDisplay version={version || "unknown"} updaterDevMode={updaterDevMode} /></span>
                </div>
              </header>

              <div className="about-details-grid">
                <div className="about-detail-item">
                  <span className="about-detail-label">Desktop shell</span>
                  <strong className="about-detail-value">Electron renderer with Python backend</strong>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Platform</span>
                  <strong className="about-detail-value">{platformName}</strong>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Current refresh</span>
                  <strong className="about-detail-value">{ui.current_auto_refresh_enabled ? `${ui.current_refresh_interval_sec || 5}s` : "disabled"}</strong>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">All refresh</span>
                  <strong className="about-detail-value">{ui.all_auto_refresh_enabled ? `${ui.all_refresh_interval_min || 5}m` : "disabled"}</strong>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Stable web panel</span>
                  <strong className="about-detail-value">Available through `codex-account ui`</strong>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Project</span>
                  <a
                    className="about-backend-link about-detail-value"
                    href={projectUrl}
                    onClick={(event) => {
                      event.preventDefault();
                      onOpenExternal(projectUrl);
                    }}
                  >
                    github.com/alisinaee/Codex-Account-Manager
                  </a>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Author</span>
                  <span className="about-detail-value">
                    Ali Sinaee
                    {" · "}
                    <a
                      className="about-backend-link"
                      href={authorGithubUrl}
                      onClick={(event) => {
                        event.preventDefault();
                        onOpenExternal(authorGithubUrl);
                      }}
                    >
                      GitHub
                    </a>
                    {" · "}
                    <a
                      className="about-backend-link"
                      href={authorLinkedinUrl}
                      onClick={(event) => {
                        event.preventDefault();
                        onOpenExternal(authorLinkedinUrl);
                      }}
                    >
                      LinkedIn
                    </a>
                  </span>
                </div>
                <div className="about-detail-item">
                  <span className="about-detail-label">Backend</span>
                  <a
                    className="about-backend-link about-detail-value"
                    href={backendUrl}
                    onClick={(event) => {
                      event.preventDefault();
                      onOpenExternal(backendUrl);
                    }}
                  >
                    {backendUrl}
                  </a>
                </div>
              </div>

              <div className="tech-pill-row">
                <span className="chip chip-neutral">Electron</span>
                <span className="chip chip-neutral">React</span>
                <span className="chip chip-neutral">Python API</span>
                <span className="chip chip-neutral">Playwright Tests</span>
              </div>
            </div>
          </SettingsCardShell>
        </div>
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
                  <div className="runtime-action-primary">
                    <Button
                      variant="primary"
                      loading={busy}
                      onClick={primaryAction.onClick}
                      disabled={primaryAction.disabled}
                    >
                      {primaryAction.label}
                    </Button>
                  </div>
                  <div className="runtime-action-meta">
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
  const isWindowsDesktop = String(desktop?.platform || "").toLowerCase() === "win32";
  const isMacDesktop = String(desktop?.platform || "").toLowerCase() === "darwin";
  const { showToast } = useToast();
  const [activeView, setActiveView] = useState("profiles");
  const [viewportSizeClass, setViewportSizeClass] = useState(() => classifyWidth(window.innerWidth));
  const [sidebarMode, setSidebarMode] = useState("fixed");
  const [state, setState] = useState(null);
  const [backendState, setBackendState] = useState(null);
  const [releaseNotes, setReleaseNotes] = useState(null);
  const [updateStatus, setUpdateStatus] = useState(null);
  const [desktopVersion, setDesktopVersion] = useState(SIDEBAR_APP_VERSION_FALLBACK);
  const [updaterDevMode, setUpdaterDevMode] = useState(false);
  const [checkingUpdateStatus, setCheckingUpdateStatus] = useState(false);
  const [updateRunning, setUpdateRunning] = useState(false);
  const [systemPythonSelection, setSystemPythonSelection] = useState("skip");
  const [backendDebugLogs, setBackendDebugLogs] = useState([]);
  const [desktopDebugLogs, setDesktopDebugLogs] = useState([]);
  const [debugCaptureEnabled, setDebugCaptureEnabled] = useState(loadDebugCapturePreference());
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState("");
  const [activatedProfile, setActivatedProfile] = useState("");
  const [switchMotion, setSwitchMotion] = useState(null);
  const [profileDeckOrder, setProfileDeckOrder] = useState([]);
  const [autoArrangeBusy, setAutoArrangeBusy] = useState(false);
  const [error, setErrorState] = useState("");
  const [errorDismissAt, setErrorDismissAt] = useState(0);
  const [columnPrefs, setColumnPrefs] = useState(loadStoredColumns());
  const [columnWidthResizeEnabled, setColumnWidthResizeEnabled] = useState(loadStoredColumnWidthResizeEnabled());
  const [columnWidthOverrides, setColumnWidthOverrides] = useState(loadStoredColumnWidthOverrides());
  const [windowsSwitchRestartDialogSuppressed, setWindowsSwitchRestartDialogSuppressed] = useState(loadWindowsSwitchRestartDialogPreference());
  const [sort, setSort] = useState({ key: "profile", dir: "asc" });
  const [modal, setModal] = useState(null);
  const [runtimeStatus, setRuntimeStatus] = useState({ phase: "checking_runtime", python: {}, core: {}, uiService: {}, errors: [] });
  const [runtimeProgress, setRuntimeProgress] = useState([]);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const switchControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const exportSelectionRef = useRef([]);
  const [autoChain, setAutoChain] = useState(() => normalizeChainPayload({}));
  const stateRef = useRef(null);
  const backendStateRef = useRef(null);
  const configRevisionRef = useRef(null);
  const configSaveQueueRef = useRef(Promise.resolve());
  const pendingConfigSavesRef = useRef(0);
  const refreshRunningRef = useRef(false);
  const currentRefreshRunningRef = useRef(false);
  const allRefreshRunningRef = useRef(false);
  const autoSwitchRefreshRunningRef = useRef(false);
  const sessionUsageCacheRef = useRef(null);
  const usageFlashUntilRef = useRef({});
  const restartInFlightRef = useRef(false);
  const startupAllRefreshStartedRef = useRef(false);
  const currentRefreshTimerRef = useRef(null);
  const allRefreshTimerRef = useRef(null);
  const autoSwitchStateTimerRef = useRef(null);
  const debugCaptureTimerRef = useRef(null);
  const desktopLogSigRef = useRef({ sig: "", ts: 0 });
  const [clockTick, setClockTick] = useState(Date.now());
  const debugLogs = useMemo(() => mergeDebugLogs(backendDebugLogs, desktopDebugLogs), [backendDebugLogs, desktopDebugLogs]);

  const activeTitle = useMemo(() => views.find((view) => view.id === activeView)?.label || "Profiles", [activeView]);
  const updateAvailable = !!updateStatus?.update_available;
  const visibleColumns = useMemo(() => normalizeColumns(columnPrefs), [columnPrefs]);
  const normalizedColumnWidthOverrides = useMemo(
    () => normalizeProfileColumnWidthOverrides(columnWidthOverrides),
    [columnWidthOverrides],
  );
  const errorCountdownSeconds = useMemo(
    () => (error ? getErrorBannerCountdownSeconds(errorDismissAt, clockTick) : 0),
    [clockTick, error, errorDismissAt],
  );
  const compactMode = viewportSizeClass === "size-compact";
  const effectiveSidebarMode = compactMode ? "minimal" : sidebarMode;
  const chainMetricsByName = useMemo(() => {
    const metrics = new Map();
    for (const item of autoChain.items) {
      const name = String(item?.name || "").trim();
      if (!name) {
        continue;
      }
      metrics.set(name, {
        usage5: clampPercent(item?.remaining_5h),
        usageWeekly: clampPercent(item?.remaining_weekly),
      });
    }
    for (const row of buildProfileRows(state)) {
      const name = String(row?.name || "").trim();
      if (!name) {
        continue;
      }
      const existing = metrics.get(name) || {};
      metrics.set(name, {
        usage5: existing.usage5 === null || existing.usage5 === undefined ? usageValue(row, "usage_5h") : existing.usage5,
        usageWeekly: existing.usageWeekly === null || existing.usageWeekly === undefined ? usageValue(row, "usage_weekly") : existing.usageWeekly,
      });
    }
    return metrics;
  }, [autoChain, state]);

  function notifySuccess(title, description = "") {
    showToast({ tone: "success", title, description });
  }

  function appendDesktopLog(level, message, details = {}) {
    if (!debugCaptureEnabled) return null;
    const cleanMessage = String(message || "").trim();
    if (!cleanMessage) return null;
    const sig = `${String(level || "info").toLowerCase()}|${cleanMessage}|${JSON.stringify(details || {})}`;
    const now = Date.now();
    if (desktopLogSigRef.current.sig === sig && now - desktopLogSigRef.current.ts < 1200) {
      return null;
    }
    desktopLogSigRef.current = { sig, ts: now };
    const entry = buildDesktopLogEntry(level, cleanMessage, details);
    setDesktopDebugLogs((current) => [...current, entry].slice(-240));
    return entry;
  }

  function reportAppError(errorLike, details = {}) {
    const message = errorLike?.message || String(errorLike || "");
    if (message) {
      appendDesktopLog("error", message, details);
    }
    return message;
  }

  function setError(nextError) {
    setErrorState((current) => {
      const next = typeof nextError === "function" ? nextError(current) : nextError;
      const message = String(next || "").trim();
      if (message && message !== String(current || "").trim()) {
        appendDesktopLog("error", message, { source: "renderer:setError" });
      }
      setErrorDismissAt(message ? Date.now() + ERROR_BANNER_AUTO_DISMISS_MS : 0);
      return next;
    });
  }

  function closeErrorBanner() {
    setError("");
  }

  useEffect(() => {
    if (!error) return;
    showToast({ tone: "danger", title: "Action failed", description: error });
  }, [error, showToast]);

  useEffect(() => {
    if (!error || !errorDismissAt) {
      return;
    }
    if (clockTick < errorDismissAt) {
      return;
    }
    setError("");
  }, [clockTick, error, errorDismissAt]);

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
      setAutoChain(normalizeChainPayload(chain));
    }
    if (nextState?.config?.ui) {
      setColumnPrefs(normalizeColumns(nextState.config.ui.column_prefs));
      const nextResizeEnabled = normalizeColumnWidthResizeEnabled(nextState.config.ui.column_width_resize_enabled);
      const nextWidthOverrides = normalizeProfileColumnWidthOverrides(nextState.config.ui.column_width_overrides);
      setColumnWidthResizeEnabled(nextResizeEnabled);
      setColumnWidthOverrides(nextWidthOverrides);
      saveStoredColumns(nextState.config.ui.column_prefs || defaultColumns);
      saveStoredColumnWidthResizeEnabled(nextResizeEnabled);
      saveStoredColumnWidthOverrides(nextWidthOverrides);
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
    if (nextConfig?.ui) {
      const normalized = normalizeColumns(nextConfig.ui.column_prefs);
      const nextResizeEnabled = normalizeColumnWidthResizeEnabled(nextConfig.ui.column_width_resize_enabled);
      const nextWidthOverrides = normalizeProfileColumnWidthOverrides(nextConfig.ui.column_width_overrides);
      setColumnPrefs(normalized);
      setColumnWidthResizeEnabled(nextResizeEnabled);
      setColumnWidthOverrides(nextWidthOverrides);
      saveStoredColumns(normalized);
      saveStoredColumnWidthResizeEnabled(nextResizeEnabled);
      saveStoredColumnWidthOverrides(nextWidthOverrides);
    }
  }

  function applyUpdateStatusPayload(nextStatus) {
    if (!nextStatus || typeof nextStatus !== "object") {
      return;
    }
    setUpdateStatus(nextStatus);
    setUpdaterDevMode(Boolean(nextStatus.updater_dev_mode));
    if (nextStatus.release_notes) {
      setReleaseNotes(nextStatus.release_notes);
    }
    const nextVersion = String(nextStatus.current_version || "").trim();
    if (nextVersion) {
      setDesktopVersion(nextVersion);
    }
    setSystemPythonSelection((current) => {
      if (nextStatus?.system_python?.required) {
        return "update";
      }
      if (nextStatus?.system_python?.optional) {
        return current === "update" ? "update" : "skip";
      }
      return "skip";
    });
  }

  function applyUsageState(nextUsage, { showLoading = false } = {}) {
    const prevUsageForFlash = (!showLoading
      && sessionUsageCacheRef.current
      && Array.isArray(sessionUsageCacheRef.current.profiles)
      && sessionUsageCacheRef.current.profiles.length)
      ? sessionUsageCacheRef.current
      : null;
    if (nextUsage && !nextUsage.__error) {
      if (!showLoading && prevUsageForFlash) {
        markUsageFlashUpdates(prevUsageForFlash, nextUsage, usageFlashUntilRef.current);
      }
      sessionUsageCacheRef.current = nextUsage;
    }
    setState((current) => {
      if (!current) {
        return current;
      }
      const nextState = { ...current, usage: nextUsage };
      stateRef.current = nextState;
      return nextState;
    });
  }

  function maybeShowWindowsSwitchRestartDialog() {
    if (!isWindowsDesktop || windowsSwitchRestartDialogSuppressed) {
      return;
    }
    setModal({ type: "switch-restart-warning", dontShowAgain: false });
  }

  function shouldPromptManualMacRestartAfterSwitch(profileName) {
    if (!isMacDesktop) {
      return false;
    }
    const target = String(profileName || "").trim();
    if (!target) {
      return false;
    }
    const rows = Array.isArray(stateRef.current?.usage?.profiles) ? stateRef.current.usage.profiles : [];
    const row = rows.find((item) => String(item?.name || "").trim() === target);
    if (!row) {
      return false;
    }
    return isAuthExpiredLabel(usageErrorLabel(row.error));
  }

  function closeWindowsSwitchRestartDialog(dontShowAgain) {
    if (dontShowAgain) {
      setWindowsSwitchRestartDialogSuppressed(true);
      saveWindowsSwitchRestartDialogPreference(true);
    }
    setModal((current) => (current?.type === "switch-restart-warning" ? null : current));
  }

  function commitUsagePayload(payload, opts = {}) {
    if (!payload || payload.__error) return false;
    const merged = mergeUsagePayload(
      stateRef.current?.usage,
      payload,
      stateRef.current?.list,
      stateRef.current?.current,
    );
    applyUsageState(merged, { showLoading: !!opts.showLoading });
    return true;
  }

  function setProfileLoadingState(name, loading, errorMsg = null) {
    const target = String(name || "").trim();
    if (!target) return false;
    let changed = false;
    setState((current) => {
      const usage = current?.usage;
      if (!usage || !Array.isArray(usage.profiles) || !usage.profiles.length) {
        return current;
      }
      const nextProfiles = usage.profiles.map((profile) => {
        if (String(profile?.name || "").trim() !== target) {
          return profile;
        }
        changed = true;
        return {
          ...profile,
          loading_usage: !!loading,
          error: loading ? null : (errorMsg || profile.error || null),
        };
      });
      if (!changed) {
        return current;
      }
      const nextState = {
        ...current,
        usage: {
          ...usage,
          profiles: nextProfiles,
        },
      };
      stateRef.current = nextState;
      return nextState;
    });
    return changed;
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
        reportAppError(error, {
          channel: "desktop:request",
          path,
          method: String(options?.method || "GET").toUpperCase(),
        });
        throw error;
      }
      await desktop.refresh().catch(() => null);
      try {
        return await desktop.request(path, options);
      } catch (retryError) {
        reportAppError(retryError, {
          channel: "desktop:request",
          path,
          method: String(options?.method || "GET").toUpperCase(),
          retry: true,
        });
        throw retryError;
      }
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

  async function loadAll(opts = {}) {
    const runOpts = opts || {};
    const showLoading = !!runOpts.showLoading;
    const clearUsageCache = !!runOpts.clearUsageCache;
    const forceReleaseNotes = !!runOpts.forceReleaseNotes;
    refreshRunningRef.current = true;
    setLoading(true);
    setError("");
    try {
      if (clearUsageCache) {
        sessionUsageCacheRef.current = null;
        usageFlashUntilRef.current = {};
      }
      const usageSeed = clearUsageCache ? null : stateRef.current?.usage;
      const loadingSnapshot = buildUsageLoadingSnapshot(
        usageSeed,
        stateRef.current?.list,
        stateRef.current?.current,
        "request pending",
        true,
      );
      const hasLiveUsage = Array.isArray(stateRef.current?.usage?.profiles) && stateRef.current.usage.profiles.length;
      if (Array.isArray(loadingSnapshot?.profiles) && loadingSnapshot.profiles.length) {
        if (showLoading || !hasLiveUsage) {
          applyUsageState(loadingSnapshot, { showLoading: true });
        }
      }
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
      const [update, logs, chain] = await Promise.all([
        desktop.getUpdateStatus({ force: forceReleaseNotes }),
        request(appendSessionToken("/api/debug/logs?tail=240", backend?.token), {}),
        request("/api/auto-switch/chain", {}),
      ]);
      applyDesktopState(core, { backend, chain });
      if (core?.usage && !core.usage.__error) {
        sessionUsageCacheRef.current = core.usage;
      }
      applyUpdateStatusPayload(update);
      setBackendDebugLogs(Array.isArray(logs?.logs) ? logs.logs : Array.isArray(logs) ? logs : []);
    } catch (err) {
      reportAppError(err, { action: "loadAll" });
      if (sessionUsageCacheRef.current) {
        applyUsageState(sessionUsageCacheRef.current, { showLoading: false });
      }
      setError(err?.message || String(err));
    } finally {
      refreshRunningRef.current = false;
      setLoading(false);
    }
  }

  async function refreshState() {
    await loadAll({ showLoading: true, clearUsageCache: true });
  }

  async function refreshCurrentUsage({ timeoutSec = 6 } = {}) {
    if (refreshRunningRef.current || currentRefreshRunningRef.current || !isRuntimeOperational(runtimeStatus)) {
      return;
    }
    currentRefreshRunningRef.current = true;
    try {
      const usage = await request(`/api/usage-local/current?timeout=${encodeURIComponent(String(Math.max(1, timeoutSec)))}`, {});
      if (!commitUsagePayload(usage, { showLoading: false })) {
        throw new Error("request failed");
      }
    } catch (err) {
      setError((current) => current || formatUsageRefreshError(err, { scope: "current" }));
    } finally {
      currentRefreshRunningRef.current = false;
    }
  }

  async function refreshProfileUsage(name, { timeoutSec = 7 } = {}) {
    const target = String(name || "").trim();
    if (!target) return;
    setProfileLoadingState(target, true, null);
    try {
      const usage = await request(
        `/api/usage-local/profile?name=${encodeURIComponent(target)}&timeout=${encodeURIComponent(String(Math.max(1, timeoutSec)))}`,
        {},
      );
      if (!commitUsagePayload(usage, { showLoading: false })) {
        throw new Error("request failed");
      }
    } catch (err) {
      const message = formatUsageRefreshError(err, { scope: "profile", profileName: target });
      setProfileLoadingState(target, false, message);
      setError((current) => current || message);
    }
  }

  async function refreshAllAccountsUsage({ timeoutSec = 7 } = {}) {
    if (refreshRunningRef.current || allRefreshRunningRef.current || !isRuntimeOperational(runtimeStatus)) {
      return;
    }
    allRefreshRunningRef.current = true;
    try {
      const listProfiles = Array.isArray(stateRef.current?.list?.profiles) ? stateRef.current.list.profiles : [];
      const cachedProfiles = Array.isArray(stateRef.current?.usage?.profiles) ? stateRef.current.usage.profiles : [];
      const currentName = String(
        stateRef.current?.usage?.current_profile
        || cachedProfiles.find((profile) => profile?.is_current)?.name
        || "",
      ).trim();
      const orderedNames = [];
      listProfiles.forEach((profile) => {
        const name = String(profile?.name || "").trim();
        if (name && !orderedNames.includes(name)) orderedNames.push(name);
      });
      if (!orderedNames.length) {
        cachedProfiles.forEach((profile) => {
          const name = String(profile?.name || "").trim();
          if (name && !orderedNames.includes(name)) orderedNames.push(name);
        });
      }
      for (const name of orderedNames) {
        if (refreshRunningRef.current) break;
        if (currentName && name === currentName) continue;
        await refreshProfileUsage(name, { timeoutSec });
      }
    } catch (err) {
      setError((current) => current || formatUsageRefreshError(err, { scope: "all" }));
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
        setAutoChain(normalizeChainPayload(chain));
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
    const baseProfiles = sortRows(buildProfileRows(stateRef.current || state), sort);
    const displayedProfiles = buildRowsByNameOrder(baseProfiles, profileDeckOrder);
    const displayedNames = displayedProfiles.map((profile) => profile.name);
    const { affectedNames, nextRows: nextProfiles } = buildSwitchAnimationPreview(displayedProfiles, target);
    const fromRects = captureProfileTableRowRects();
    const promptManualMacRestart = shouldPromptManualMacRestartAfterSwitch(target);
    if (!switchControllerRef.current) {
      switchControllerRef.current = createSwitchController((profileName, options = {}) => desktop.switchProfile(profileName, options));
    }
    setSwitching(target);
    setActivatedProfile("");
    setError("");
    setProfileDeckOrder(nextProfiles.map((profile) => profile.name));
    setSwitchMotion({
      token: `${Date.now()}-${target}`,
      target,
      affectedNames,
      fromRects,
    });
    try {
      const switchOptions = buildDesktopSwitchOptions({ platform: desktop?.platform });
      const next = await switchControllerRef.current.switchProfile(target, switchOptions);
      applyDesktopState(next);
      loadAll({ showLoading: false, clearUsageCache: true }).catch(() => {});
      setActivatedProfile(target);
      notifySuccess("Profile switched", `Current profile: ${target}`);
      maybeShowWindowsSwitchRestartDialog();
      if (promptManualMacRestart && switchOptions.noRestart === true) {
        setModal({
          type: "mac-auth-expired-restart-warning",
          profileName: target,
        });
      }
      setTimeout(() => setActivatedProfile((current) => (current === target ? "" : current)), 1100);
    } catch (err) {
      setProfileDeckOrder(displayedNames);
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

  async function setThemeMode(themeMode) {
    await saveUiPatch({ ui: { theme: themeMode } });
  }

  function cycleThemeMode() {
    return setThemeMode(getNextThemeMode(state?.config?.ui?.theme));
  }

  async function toggleDebug() {
    const current = !!state?.config?.ui?.debug_mode;
    await saveUiPatch({ ui: { debug_mode: !current } });
  }

  async function checkForUpdates() {
    setCheckingUpdateStatus(true);
    try {
      const next = await desktop.getUpdateStatus({ force: true });
      applyUpdateStatusPayload(next);
      setActiveView("update");
      notifySuccess("Update check complete", next?.status_text || "Status refreshed.");
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setCheckingUpdateStatus(false);
    }
  }

  async function runUpdate() {
    setModal({
      type: "update-progress",
      phase: "checking_updates",
      label: "Checking updates",
      status: "running",
      percent: 5,
      targetVersion: updateStatus?.latest_version || desktopVersion,
      detail: "Preparing the unified desktop update flow.",
      logs: [],
      dismissible: false,
      error: "",
    });
    setUpdateRunning(true);
    try {
      const next = await desktop.runUnifiedUpdate({ systemPythonSelection });
      applyUpdateStatusPayload(next);
      if (!next?.desktop_update_needed) {
        await loadAll({ showLoading: false, clearUsageCache: true });
      }
      setActiveView("update");
    } catch (err) {
      setModal((current) => (
        current?.type === "update-progress"
          ? {
            ...current,
            phase: "failed",
            label: "Update failed",
            status: "failed",
            percent: 100,
            detail: err?.message || String(err),
            error: err?.message || String(err),
            dismissible: true,
          }
          : current
      ));
    } finally {
      setUpdateRunning(false);
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
      triggerBlobDownload(blob, `codex-account-debug-${Date.now()}.json`, { revokeDelayMs: 1200 });
      notifySuccess("Debug export ready", "Saved desktop debug snapshot.");
    } catch (err) {
      setError(err?.message || String(err));
    }
  }

  function setColumnWidthResizeMode(nextValue, { persist = true } = {}) {
    const normalized = normalizeColumnWidthResizeEnabled(nextValue);
    setColumnWidthResizeEnabled(normalized);
    saveStoredColumnWidthResizeEnabled(normalized);
    if (persist) {
      saveUiPatch({ ui: { column_width_resize_enabled: normalized } }).catch(() => {});
    }
  }

  function applyColumnWidthOverrides(nextOverrides, { persist = false } = {}) {
    const normalized = normalizeProfileColumnWidthOverrides(nextOverrides);
    setColumnWidthOverrides(normalized);
    saveStoredColumnWidthOverrides(normalized);
    if (persist) {
      saveUiPatch({
        ui: {
          column_width_overrides: Object.keys(normalized).length ? normalized : null,
        },
      }).catch(() => {});
    }
  }

  function resetColumnWidthOverridesOnly() {
    applyColumnWidthOverrides({}, { persist: true });
  }

  function resetColumnPreferencesToDefault() {
    setColumnPrefs(defaultColumns);
    saveStoredColumns(defaultColumns);
    setColumnWidthResizeEnabled(false);
    saveStoredColumnWidthResizeEnabled(false);
    setColumnWidthOverrides({});
    saveStoredColumnWidthOverrides({});
    saveUiPatch({
      ui: {
        column_prefs: defaultColumns,
        column_width_resize_enabled: false,
        column_width_overrides: null,
      },
    }).catch(() => {});
    setModal(null);
  }

  function handleColumnResize(columnKey, nextWidth, { commit = false } = {}) {
    if (!columnWidthResizeEnabled) {
      return;
    }
    const key = String(columnKey || "").trim();
    if (!isProfileColumnResizable(key)) {
      return;
    }
    const widthMatch = String(nextWidth || "").trim().match(/^([0-9]+(?:\.[0-9]+)?)px$/);
    if (!widthMatch) {
      return;
    }
    const clamped = clampProfileColumnWidthPx(key, Number(widthMatch[1]));
    if (!Number.isFinite(clamped)) {
      return;
    }
    const resolvedWidth = `${clamped}px`;
    const nextOverrides = {
      ...normalizedColumnWidthOverrides,
      [key]: resolvedWidth,
    };
    applyColumnWidthOverrides(nextOverrides, { persist: commit });
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

  async function openAccountDetails(profile) {
    if (!profile?.name) return;
    setModal({
      type: "account-details",
      profile: { ...profile },
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

  function resolveProfileEmailByName(name) {
    const target = String(name || "").trim();
    if (!target) return "";
    const rows = buildProfileRows(stateRef.current || state);
    const row = rows.find((item) => String(item?.name || "").trim() === target);
    if (!row) {
      return isLikelyEmail(target) ? target : "";
    }
    return (
      String(row.email_display || row.email || "").trim()
      || extractEmailFromHint(row.account_hint || "")
      || (isLikelyEmail(target) ? target : "")
    );
  }

  async function openAddAccount() {
    setModal({ type: "add-account", name: "", email: "", mode: "device", session: null, busy: false, detecting: false, completed: false, successMessage: "" });
  }

  async function openExportProfiles() {
    const rows = buildProfileRows(state)
      .map((row) => ({
        name: String(row?.name || "").trim(),
        email: String(row?.email_display || row?.email || "").trim() || "-",
      }))
      .filter((row) => row.name);
    const allNames = ensureUniqueNames(rows.map((row) => row.name));
    exportSelectionRef.current = allNames;
    setModal({ type: "export", filename: "profiles", rows, allNames, selected: allNames, exporting: false });
  }

  async function openImportProfiles() {
    setModal({ type: "import-warning-choose" });
  }

  function getChainEditSourceNames() {
    const names = normalizeChainNames([
      ...autoChain.chain,
      ...autoChain.manual_chain,
    ]);
    if (names.length) {
      return names;
    }
    return normalizeChainNames(buildProfileRows(state).map((row) => row.name));
  }

  function getActiveChainName() {
    const first = String(autoChain.chain[0] || "").trim();
    if (first) {
      return first;
    }
    const currentName = String(state?.usage?.current_profile || state?.current?.profile_name || "").trim();
    return currentName || "";
  }

  async function openChainEditor() {
    const lockedName = getActiveChainName();
    const chain = ensureLockedChainOrder(getChainEditSourceNames(), lockedName);
    setModal({ type: "chain-edit", chain, lockedName });
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

  async function testNotif() {
    try {
      await request("/api/auto-switch/test-notif", { method: "POST", body: JSON.stringify({}) });
      await Promise.all([
        refreshAutoSwitchState(),
        loadAll(),
      ]);
      setActiveView("autoswitch");
      notifySuccess("Notification test armed", "Pending auto-switch started. Use Stop switch to cancel before it runs.");
    } catch (err) {
      const msg = String(err?.message || err || "");
      if (/endpoint not found/i.test(msg)) {
        setError("Desktop backend is running old code. Restart UI service from Update/System, then run Test notif again.");
        return;
      }
      setError(msg);
    }
  }

  async function stopAutoSwitch() {
    try {
      await request("/api/auto-switch/stop", { method: "POST", body: JSON.stringify({}) });
      await Promise.all([
        refreshAutoSwitchState(),
        loadAll(),
      ]);
      setModal({
        type: "auto-switch-stopped-warning",
        title: "Auto-switch disabled",
        message: "Auto-switch has been disabled. Enable it again from Auto Switch rules when you want automatic switching to resume.",
      });
      setActiveView("autoswitch");
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
    if (autoArrangeBusy) return;
    setAutoArrangeBusy(true);
    try {
      const next = await request("/api/auto-switch/auto-arrange", { method: "POST", body: JSON.stringify({}) });
      setAutoChain(normalizeChainPayload(next));
      await Promise.all([
        refreshAutoSwitchState().catch(() => {}),
        refreshCurrentUsage({ timeoutSec: 8 }).catch(() => {}),
      ]);
      notifySuccess("Chain reordered");
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setAutoArrangeBusy(false);
    }
  }

  async function startAddAccount(mode, name, options = {}) {
    const target = String(name || "").trim();
    if (!target) return;
    const payload = await request(
      "/api/local/add/start",
      {
        method: "POST",
        body: JSON.stringify({
          name: target,
          timeout: 600,
          device_auth: mode === "device",
          force: Boolean(options?.force),
        }),
      },
    );
    setModal((current) => ({
      ...current,
      busy: false,
      detecting: false,
      completed: false,
      successMessage: "",
      session: payload,
    }));
  }

  function openAuthRelogin(profileInput) {
    const profileName = typeof profileInput === "string" ? profileInput : profileInput?.name;
    const target = String(profileName || "").trim();
    if (!target) return;
    let email = "";
    if (profileInput && typeof profileInput === "object") {
      email = String(profileInput.email_display || profileInput.email || "").trim();
      if (!email) {
        email = extractEmailFromHint(profileInput.account_hint || "");
      }
    }
    if (!email) {
      const usageRows = Array.isArray(stateRef.current?.usage?.profiles) ? stateRef.current.usage.profiles : [];
      const usageRow = usageRows.find((row) => String(row?.name || "").trim() === target);
      if (usageRow) {
        email = String(usageRow.email_display || usageRow.email || "").trim() || extractEmailFromHint(usageRow.account_hint || "");
      }
    }
    if (!email) {
      const listRows = Array.isArray(stateRef.current?.list?.profiles) ? stateRef.current.list.profiles : [];
      const listRow = listRows.find((row) => String(row?.name || "").trim() === target);
      if (listRow) {
        email = extractEmailFromHint(listRow.account_hint || "");
      }
    }
    setModal({ type: "auth-relogin", name: target, email, mode: "device", session: null, busy: false, detecting: false, completed: false, successMessage: "" });
  }

  async function cancelLoginSession(sessionId) {
    const sid = String(sessionId || "").trim();
    if (!sid) return;
    await request("/api/local/add/cancel", {
      method: "POST",
      body: JSON.stringify({ id: sid }),
    });
  }

  function triggerImportArchivePicker() {
    const input = fileInputRef.current;
    if (!input) return;
    window.setTimeout(() => input.click(), 0);
  }

  function openImportAnalyzeStep(file) {
    if (!file) return;
    setModal({ type: "import-warning-analyze", file, busy: false });
  }

  function updateImportPlanRow(name, patch) {
    const target = String(name || "").trim();
    if (!target) return;
    setModal((current) => {
      if (!current || (current.type !== "import-review" && current.type !== "import-review-confirm")) {
        return current;
      }
      const nextRows = (current.profiles || []).map((row) => {
        if (String(row?.name || "").trim() !== target) {
          return row;
        }
        return { ...row, ...patch };
      });
      return { ...current, profiles: nextRows };
    });
  }

  async function importAnalyze(file) {
    if (!file) return;
    setModal((current) => {
      if (!current || current.type !== "import-warning-analyze") return current;
      return { ...current, busy: true };
    });
    try {
      const content_b64 = await fileToBase64(file);
      const payload = await request("/api/local/import/analyze", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_b64 }),
      });
      setModal({
        type: "import-review",
        file,
        analysis: payload,
        profiles: cloneImportPlanRows(payload?.profiles || []),
      });
    } catch (err) {
      setModal({ type: "import-warning-analyze", file, busy: false });
      throw err;
    }
  }

  async function applyImport(analysis, profiles, { skipRiskConfirm = false } = {}) {
    const rows = cloneImportPlanRows(profiles);
    const summary = buildImportPlanSummary(rows);
    if (summary.invalidRenameCount > 0) {
      throw new Error("Set a new profile name for each Rename action before applying import.");
    }
    if (!summary.selectedCount) {
      throw new Error("Select at least one profile action other than Skip.");
    }
    if (summary.overwriteCount > 0 && !skipRiskConfirm) {
      setModal((current) => {
        if (!current || current.type !== "import-review") {
          return current;
        }
        return { ...current, type: "import-review-confirm" };
      });
      return;
    }
    await request("/api/local/import/apply", {
      method: "POST",
      body: JSON.stringify({ analysis_id: analysis?.analysis_id, profiles: rows }),
    });
    const { core, backend, extrasPromise } = await refreshProfilesAfterMutation({
      desktop,
      request,
      appendSessionTokenFn: appendSessionToken,
    });
    applyDesktopState(core, { backend });
    setModal(null);
    extrasPromise.then((extras) => {
      if (!extras || typeof extras !== "object") {
        return;
      }
      if (extras.chain !== undefined) {
        setAutoChain(normalizeChainPayload(extras.chain));
      }
      if (extras.update !== undefined) {
        applyUpdateStatusPayload({
          ...extras.update,
          release_notes: extras.notes || extras.update?.release_notes || releaseNotes,
        });
      } else if (extras.notes !== undefined) {
        setReleaseNotes(extras.notes);
      }
      if (extras.logs !== undefined) {
        setBackendDebugLogs(Array.isArray(extras.logs?.logs) ? extras.logs.logs : Array.isArray(extras.logs) ? extras.logs : []);
      }
    }).catch(() => {});
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
    if (!Array.isArray(names) || names.length < 1) {
      throw new Error("Select at least one profile to export.");
    }
    const payload = await request("/api/local/export/prepare", {
      method: "POST",
      body: JSON.stringify({ scope: "selected", names, filename }),
    });
    if (typeof desktop?.downloadExport !== "function") {
      throw new Error("desktop export is unavailable");
    }
    const saved = await desktop.downloadExport(
      payload.export_id,
      payload.filename || `${filename || "profiles"}.camzip`,
    );
    if (saved?.canceled) {
      setModal((current) => (current && current.type === "export" ? { ...current, exporting: false } : current));
      return;
    }
    setModal(null);
    await loadAll();
    notifySuccess("Export ready", "The selected profiles were exported.");
  }

  async function loadReleaseNotes(force = false) {
    const next = await desktop.getUpdateStatus({ force });
    applyUpdateStatusPayload(next);
  }

  async function loadDebugLogs() {
    const logs = await request(appendSessionToken(`/api/debug/logs?tail=240&t=${Date.now()}`, backendState?.token), {});
    const rows = Array.isArray(logs?.logs) ? logs.logs : Array.isArray(logs) ? logs : [];
    setBackendDebugLogs(rows);
  }

  function startDebugCapture() {
    setDebugCaptureEnabled(true);
    saveDebugCapturePreference(true);
    loadDebugLogs().catch((err) => setError(err?.message || String(err)));
  }

  async function forceRefreshUsage({ timeoutSec = 8 } = {}) {
    const usage = await request(
      `/api/usage-local?force=true&timeout=${encodeURIComponent(String(Math.max(1, timeoutSec)))}`,
      {},
    );
    if (!commitUsagePayload(usage, { showLoading: false })) {
      throw new Error("request failed");
    }
  }

  function stopDebugCapture() {
    setDebugCaptureEnabled(false);
    saveDebugCapturePreference(false);
  }

  function clearDebugLogs() {
    setBackendDebugLogs([]);
    setDesktopDebugLogs([]);
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

  useEffect(() => watchThemePreference(document.documentElement, state?.config?.ui?.theme || "auto"), [state?.config?.ui?.theme]);

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
    const offCycleView = desktop.onCycleView((step) => {
      setActiveView((current) => cycleViewId(current, step));
    });
    const offRefreshRequested = desktop.onRefreshRequested(() => {
      setActiveView("profiles");
      loadAll().catch(() => {});
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
    const offUpdateProgress = desktop.onUpdateProgress?.((progress) => {
      setModal((current) => (
        current?.type === "update-progress"
          ? {
            ...current,
            phase: progress?.phase || current.phase,
            label: progress?.label || current.label,
            status: progress?.status || current.status,
            percent: Number.isFinite(Number(progress?.percent)) ? Number(progress.percent) : current.percent,
            detail: progress?.detail || progress?.message || current.detail,
            targetVersion: progress?.targetVersion || current.targetVersion,
            error: progress?.error || current.error,
            dismissible: ["done", "failed"].includes(String(progress?.status || "")),
            logs: [...(current.logs || []), progress],
          }
          : current
      ));
      if (["done", "failed", "awaiting-user"].includes(String(progress?.status || ""))) {
        desktop.getUpdateStatus?.().then((next) => applyUpdateStatusPayload(next)).catch(() => {});
      }
    });
    const offAutoSwitchStopped = desktop.onAutoSwitchStopped?.((payload) => {
      const title = String(payload?.title || "Auto-switch disabled");
      const message = String(
        payload?.message
          || "Auto-switch has been disabled. Enable it again from Auto Switch rules when you want automatic switching to resume.",
      );
      setModal({
        type: "auto-switch-stopped-warning",
        title,
        message,
      });
      setActiveView("autoswitch");
    });
    const offAutoSwitchPending = desktop.onAutoSwitchPending?.((payload) => {
      const title = String(payload?.title || "Auto-switch is pending");
      const message = String(
        payload?.message
          || "Auto-switch is pending. Stop it now if you want to cancel this switch flow.",
      );
      setModal({
        type: "auto-switch-pending-warning",
        title,
        message,
      });
      setActiveView("autoswitch");
    });
    return () => {
      offNavigate?.();
      offSidebar?.();
      offCycleView?.();
      offRefreshRequested?.();
      offRuntime?.();
      offProgress?.();
      offUpdateProgress?.();
      offAutoSwitchStopped?.();
      offAutoSwitchPending?.();
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
    if (!shouldRunStartupAllAccountsRefresh({
      runtimeStatus,
      loading,
      state,
      alreadyStarted: startupAllRefreshStartedRef.current,
    })) {
      return undefined;
    }
    startupAllRefreshStartedRef.current = true;
    const timer = window.setTimeout(() => {
      refreshAllAccountsUsage({ timeoutSec: 7 }).catch(() => {});
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    loading,
    runtimeStatus?.phase,
    runtimeStatus?.python?.supported,
    runtimeStatus?.core?.installed,
    runtimeStatus?.uiService?.running,
    state?.current?.profile_name,
    state?.usage?.current_profile,
    state?.list?.profiles?.length,
    state?.usage?.profiles?.length,
  ]);

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
    if (activeView === "debug" && debugCaptureEnabled) loadDebugLogs().catch(() => {});
    if (activeView === "update") loadAll({ forceReleaseNotes: true }).catch(() => {});
  }, [activeView, debugCaptureEnabled]);

  useEffect(() => {
    if (debugCaptureTimerRef.current) {
      window.clearInterval(debugCaptureTimerRef.current);
      debugCaptureTimerRef.current = null;
    }
    if (activeView !== "debug" || !debugCaptureEnabled) {
      return undefined;
    }
    debugCaptureTimerRef.current = window.setInterval(() => {
      loadDebugLogs().catch(() => {});
    }, 1200);
    return () => {
      if (debugCaptureTimerRef.current) {
        window.clearInterval(debugCaptureTimerRef.current);
        debugCaptureTimerRef.current = null;
      }
    };
  }, [activeView, debugCaptureEnabled, backendState?.token]);

  useEffect(() => {
    const modalType = modal?.type;
    if (modalType !== "add-account" && modalType !== "auth-relogin") {
      return undefined;
    }
    const sessionId = String(modal?.session?.id || "").trim();
    const sessionStatus = String(modal?.session?.status || "").trim().toLowerCase();
    if (!sessionId || sessionStatus !== "running") {
      return undefined;
    }

    let cancelled = false;
    const tick = async () => {
      try {
        const nextSession = await request(`/api/local/add/session?id=${encodeURIComponent(sessionId)}`, {});
        if (cancelled) return;
        setModal((current) => (
          current && current.type === modalType
            ? { ...current, session: nextSession, busy: false }
            : current
        ));
        const nextStatus = String(nextSession?.status || "").trim().toLowerCase();
        if (nextStatus === "completed") {
          const targetName = String(nextSession?.name || modal?.name || "").trim();
          if (modalType === "add-account") {
            setModal((current) => (
              current && current.type === "add-account"
                ? { ...current, session: nextSession, busy: true, detecting: true, completed: false, successMessage: "" }
                : current
            ));
          }
          await loadAll({ showLoading: false, clearUsageCache: true });
          await forceRefreshUsage({ timeoutSec: 8 }).catch(() => {});
          if (targetName) {
            await refreshProfileUsage(targetName, { timeoutSec: 8 }).catch(() => {});
          }
          const refreshedEmail = resolveProfileEmailByName(targetName);
          if (cancelled) return;
          if (modalType === "add-account") {
            setModal((current) => (
              current && current.type === "add-account"
                ? {
                    ...current,
                    email: refreshedEmail || current.email || "",
                    session: nextSession,
                    busy: false,
                    detecting: false,
                    completed: true,
                    successMessage: targetName ? `Profile detected and refreshed: ${targetName}` : "Profile login finished and refreshed.",
                  }
                : current
            ));
          } else {
            setModal(null);
            notifySuccess("Login completed", targetName ? `Profile refreshed: ${targetName}` : "Profile login finished.");
          }
        } else if (nextStatus === "failed") {
          setError(nextSession?.error || "Login session failed");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || String(err));
        }
      }
    };

    const timer = window.setInterval(() => {
      tick().catch(() => {});
    }, 1400);
    tick().catch(() => {});
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [modal?.type, modal?.session?.id, modal?.session?.status]);

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
        version={desktopVersion}
        updaterDevMode={updaterDevMode}
        onExit={requestExit}
      />
      <div className="workspace">
        <TopBar
          activeTitle={activeTitle}
          updateStatus={updateStatus}
          loading={loading}
          themeMode={state?.config?.ui?.theme}
          onCycleTheme={cycleThemeMode}
          onRefresh={refreshState}
          onRestart={restartUiService}
        />
        {activeView === "profiles" && (
          <ProfilesView
            state={state}
            switching={switching}
            activatedProfile={activatedProfile}
            switchMotion={switchMotion}
            profileDeckOrder={profileDeckOrder}
            onSwitch={switchProfile}
            onAddAccount={openAddAccount}
            onImportProfiles={openImportProfiles}
            onExportProfiles={openExportProfiles}
            onRemoveAll={handleRemoveAll}
            onOpenColumns={openColumnsModal}
            onOpenRowActions={openRowActions}
            onOpenAccountDetails={openAccountDetails}
            onToggleEligibility={toggleEligibility}
            visibleColumns={visibleColumns}
            columnWidthResizeEnabled={columnWidthResizeEnabled}
            columnWidthOverrides={normalizedColumnWidthOverrides}
            sort={sort}
            compactMode={compactMode}
            viewportSizeClass={viewportSizeClass}
            shouldFlashUsageFn={(name, metric, loadingState) => shouldFlashUsage(usageFlashUntilRef.current, name, metric, loadingState)}
            onColumnResize={handleColumnResize}
            onSort={(key) => {
              setProfileDeckOrder([]);
              setSort((current) => ({ key, dir: current.key === key && current.dir === "asc" ? "desc" : "asc" }));
            }}
          />
        )}
        {activeView === "autoswitch" && (
          <AutoSwitchView
            state={state}
            autoChain={autoChain}
            onSavePatch={saveUiPatch}
            onOpenChainEdit={openChainEditor}
            onRunSwitch={runAutoSwitch}
            onRapidTest={runRapidTest}
            onStopTests={stopTests}
            onStopSwitch={stopAutoSwitch}
            onTestAutoSwitch={testAutoSwitch}
            onAutoArrange={autoArrange}
            autoArrangeBusy={autoArrangeBusy}
          />
        )}
        {activeView === "settings" && (
          <SettingsView
            state={state}
            onNotify={testNotification}
            onTestAutoSwitchNotif={testNotif}
            onSavePatch={saveUiPatch}
          />
        )}
        {activeView === "guide" && <GuideView isMacDesktop={isMacDesktop} />}
        {activeView === "update" && (
          <UpdateView
            releaseNotes={releaseNotes}
            updateStatus={updateStatus}
            currentVersion={desktopVersion}
            updaterDevMode={updaterDevMode}
            checking={checkingUpdateStatus || loading}
            updating={updateRunning}
            systemPythonSelection={systemPythonSelection}
            onCheck={checkForUpdates}
            onRunUpdate={runUpdate}
            onRefreshReleaseNotes={() => loadReleaseNotes(true).catch(() => {})}
            onSystemPythonSelectionChange={setSystemPythonSelection}
          />
        )}
        {activeView === "debug" && (
          <DebugView
            debugLogs={debugLogs}
            captureEnabled={debugCaptureEnabled}
            onStartCapture={startDebugCapture}
            onStopCapture={stopDebugCapture}
            onClear={clearDebugLogs}
            onExport={onExportDebug}
          />
        )}
        {activeView === "about" && <AboutView backendState={backendState} state={state} version={desktopVersion} updaterDevMode={updaterDevMode} onOpenExternal={(url) => desktop.openExternal(url)} />}
        {error ? (
          <div className="workspace-error" role="alert">
            <div className="workspace-error-content">
              <p className="workspace-error-message">{error}</p>
              <div className="workspace-error-actions">
                <span className="workspace-error-timer">Dismiss in {errorCountdownSeconds}s</span>
                <button
                  type="button"
                  className="dialog-close workspace-error-close"
                  onClick={closeErrorBanner}
                  aria-label="Close error"
                  title="Close error"
                >
                  <DialogCloseIcon />
                </button>
              </div>
            </div>
          </div>
        ) : null}
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

      {modal?.type === "update-progress" && (
        <UpdateProgressDialog
          modal={modal}
          onClose={() => setModal((current) => (current?.type === "update-progress" && current.dismissible ? null : current))}
          onRetry={() => {
            setModal(null);
            runUpdate().catch(() => {});
          }}
        />
      )}

      {modal?.type === "switch-restart-warning" && (
        <Dialog
          title="Restart Codex to apply Windows changes"
          size="sm"
          onClose={() => closeWindowsSwitchRestartDialog(!!modal.dontShowAgain)}
          footer={<Button variant="primary" onClick={() => closeWindowsSwitchRestartDialog(!!modal.dontShowAgain)}>OK</Button>}
        >
          <p>On Windows, close and reopen the Codex app after switching accounts so all changes apply correctly.</p>
          <label className="modal-check">
            <input
              type="checkbox"
              checked={!!modal.dontShowAgain}
              onChange={(event) => setModal((current) => (
                current?.type === "switch-restart-warning"
                  ? { ...current, dontShowAgain: event.target.checked }
                  : current
              ))}
            />
            <span>Do not show this again</span>
          </label>
        </Dialog>
      )}

      {modal?.type === "mac-auth-expired-restart-warning" && (
        <Dialog
          title="Manual restart recommended on macOS"
          size="sm"
          onClose={() => setModal(null)}
          footer={<Button variant="primary" onClick={() => setModal(null)}>OK</Button>}
        >
          <p>
            This profile appears to have expired auth. After switching, close and reopen the Codex app manually so host connections reset cleanly.
          </p>
          {modal.profileName ? <p className="muted">Switched profile: {modal.profileName}</p> : null}
        </Dialog>
      )}

      {modal?.type === "auto-switch-stopped-warning" && (
        <Dialog
          title={modal.title || "Auto-switch disabled"}
          size="sm"
          onClose={() => setModal(null)}
          footer={<Button variant="primary" onClick={() => setModal(null)}>OK</Button>}
        >
          <p>{modal.message || "Auto-switch has been disabled. Enable it again from Auto Switch rules when you want automatic switching to resume."}</p>
        </Dialog>
      )}

      {modal?.type === "auto-switch-pending-warning" && (
        <Dialog
          title={modal.title || "Auto-switch is pending"}
          size="sm"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={() => setModal(null)}>Later</Button>
              <Button
                variant="primary"
                onClick={() => {
                  setModal(null);
                  runAutoSwitch().catch((err) => setError(err?.message || String(err)));
                }}
              >
                Continue
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  setModal(null);
                  stopAutoSwitch().catch((err) => setError(err?.message || String(err)));
                }}
              >
                Stop switch
              </Button>
            </>
          )}
        >
          <p>{modal.message || "Auto-switch is pending. Stop it now if you want to cancel this switch flow."}</p>
        </Dialog>
      )}

      {modal?.type === "columns" && (
        <Dialog
          title="Table columns"
          size="md"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={resetColumnPreferencesToDefault}>Reset to default</Button>
              <Button variant="primary" onClick={() => setModal(null)}>Done</Button>
            </>
          )}
        >
          <div className="columns-grid column-resize-grid">
            <div className="modal-check">
              <span>Change columns width</span>
              <div className="column-resize-actions">
                <ToggleSwitch
                  checked={columnWidthResizeEnabled}
                  ariaLabel="Change columns width"
                  onChange={(nextValue) => setColumnWidthResizeMode(nextValue)}
                />
                <Button onClick={resetColumnWidthOverridesOnly}>Reset width</Button>
              </div>
            </div>
          </div>
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
          <div className="settings-inline-actions row-actions-grid">
            <Button onClick={() => { setModal(null); handleRename(modal.profile?.name).catch((e) => setError(e?.message || String(e))); }}>Edit</Button>
            <Button onClick={() => copyToClipboard("Email", modal.profile?.email)}>Copy email</Button>
            <Button onClick={() => copyToClipboard("ID", modal.profile?.accountId)}>Copy ID</Button>
            <Button variant="danger" onClick={() => { setModal(null); handleRemove(modal.profile?.name); }}>Remove account</Button>
          </div>
        </Dialog>
      )}

      {modal?.type === "account-details" && (() => {
        const profile = modal.profile || {};
        const h5Loading = isUsageLoadingState(profile.usage_5h, profile.error, profile.loading_usage);
        const weeklyLoading = isUsageLoadingState(profile.usage_weekly, profile.error, profile.loading_usage);
        const errorLabel = usageErrorLabel(profile.error) || formatAccountDetailValue(profile.error);
        const hasAuthExpired = isAuthExpiredLabel(errorLabel);
        const rawJson = JSON.stringify(profile, null, 2);
        return (
          <Dialog
            title={`Account details - ${profile.name || "profile"}`}
            size="lg"
            onClose={() => setModal(null)}
            footer={(
              <>
                <Button onClick={() => copyToClipboard("Account JSON", rawJson)}>Copy JSON</Button>
                <Button variant="primary" onClick={() => setModal(null)}>Done</Button>
              </>
            )}
          >
            <div className="account-details-layout">
              {hasAuthExpired ? (
                <section className="account-details-auth-warning" role="alert">
                  <div className="account-details-auth-warning-head">
                    <AuthExpiredBadge />
                    <strong>Session refresh required</strong>
                  </div>
                  <p>This profile auth snapshot is expired and cannot read usage until you refresh its session.</p>
                  <ol>
                    <li>Click <strong>Re-login profile</strong> and complete the login flow.</li>
                    <li>Wait until login status reaches <strong>completed</strong>.</li>
                    <li>The app refreshes this profile automatically after completion.</li>
                  </ol>
                  <p className="muted">Tip: if it still shows auth expired after completion, switch to the profile once and refresh usage again.</p>
                  <div className="settings-inline-actions">
                    <Button variant="primary" onClick={() => openAuthRelogin(profile)}>
                      Re-login profile
                    </Button>
                    <Button variant="primary" onClick={() => {
                      const profileName = String(profile.name || "").trim();
                      setModal(null);
                      if (profileName) {
                        switchProfile(profileName).catch((err) => setError(err?.message || String(err)));
                      }
                    }}
                    >
                      Switch now
                    </Button>
                  </div>
                </section>
              ) : null}
              <section className="account-details-hero">
                <div className="account-details-primary">
                  <div className="account-details-title-row account-details-identity">
                    <strong className="account-details-name">{profile.name || "-"}</strong>
                    <span className="account-details-sep" aria-hidden="true">•</span>
                    <span className="account-details-state">{profile.is_current ? "Current profile" : "Saved profile"}</span>
                  </div>
                  <div className="account-details-meta-row">
                    <Badge variant={planBadgeVariant(profile.plan_type)}>{String(profile.plan_type || "free")}</Badge>
                    <Badge variant={profile.is_paid ? "success" : "neutral"}>{profile.is_paid ? "Paid account" : "Free account"}</Badge>
                  </div>
                  <div className="account-details-email">{profile.email_display || profile.email || "-"}</div>
                </div>
                <div className="account-details-quick-metrics">
                  <div>
                    <span>5h usage</span>
                    <strong>{usagePercent(profile, "usage_5h")}</strong>
                  </div>
                  <div>
                    <span>Weekly usage</span>
                    <strong>{usagePercent(profile, "usage_weekly")}</strong>
                  </div>
                </div>
              </section>

              <div className="account-details-grid">
                <section className="account-details-card">
                  <h4>Identity</h4>
                  <LabelValueRow label="Profile" value={formatAccountDetailValue(profile.name)} />
                  <LabelValueRow label="Email" value={formatAccountDetailValue(profile.email_display || profile.email)} />
                  <LabelValueRow label="Account ID" value={formatAccountDetailValue(profile.account_id)} />
                  <LabelValueRow label="Added" value={formatAccountDetailValue(fmtSavedAtFull(profile.saved_at))} />
                  <LabelValueRow label="Note" value={formatAccountDetailValue(profile.note)} />
                </section>

                <section className="account-details-card">
                  <h4>Usage Windows</h4>
                  <LabelValueRow label="5h usage" value={usagePercent(profile, "usage_5h")} />
                  <LabelValueRow label="5h remain" value={formatRemainCell(profile.usage_5h?.resets_at, true, h5Loading, profile.error)} />
                  <LabelValueRow label="5h reset at" value={formatAccountDetailValue(fmtResetFull(profile.usage_5h?.resets_at))} />
                  <LabelValueRow label="Weekly usage" value={usagePercent(profile, "usage_weekly")} />
                  <LabelValueRow label="Weekly remain" value={formatRemainCell(profile.usage_weekly?.resets_at, false, weeklyLoading, profile.error)} />
                  <LabelValueRow label="Weekly reset at" value={formatAccountDetailValue(fmtResetFull(profile.usage_weekly?.resets_at))} />
                </section>

                <section className="account-details-card">
                  <h4>Flags & Status</h4>
                  <LabelValueRow label="Current profile" value={formatAccountDetailValue(profile.is_current)} />
                  <LabelValueRow label="Auto-switch eligible" value={formatAccountDetailValue(profile.auto_switch_eligible)} />
                  <LabelValueRow label="Same principal" value={formatAccountDetailValue(profile.same_principal)} />
                  <LabelValueRow label="Plan type" value={formatAccountDetailValue(profile.plan_type || "free")} />
                  <LabelValueRow label="Paid account" value={formatAccountDetailValue(profile.is_paid)} />
                  <LabelValueRow label="Last error" value={hasAuthExpired ? <AuthExpiredBadge /> : formatAccountDetailValue(profile.error)} />
                </section>
              </div>

              <section className="account-details-card account-details-raw">
                <h4>Raw account payload</h4>
                <pre>{rawJson}</pre>
              </section>
            </div>
          </Dialog>
        );
      })()}

      {modal?.type === "add-account" && (
        (() => {
          const loginUrlValue = resolveSessionLoginUrl(modal.session, modal.mode);
          const canCopyLoginUrl = isCopyableUrl(loginUrlValue);
          const emailValue = String(modal.email || resolveProfileEmailByName(modal.name) || "").trim();
          const canCopyEmail = isLikelyEmail(emailValue);
          return (
        <Dialog title="Add account" size="md" onClose={() => setModal(null)} footer={<Button onClick={() => setModal(null)}>Close</Button>}>
          <div className="modal-form">
            <p className="muted">Create or refresh a saved profile with the selected login flow.</p>
            <label>Profile name</label>
            <input
              value={modal.name}
              onChange={(event) => setModal((current) => ({
                ...current,
                name: event.target.value,
                email: isLikelyEmail(event.target.value) ? event.target.value.trim() : current.email,
              }))}
              placeholder="work"
            />
            <label>Login mode</label>
            <select value={modal.mode} onChange={(event) => setModal((current) => ({ ...current, mode: event.target.value }))}>
              <option value="device">Device Login</option>
              <option value="normal">Normal Login</option>
            </select>
            <LoginModeHelp mode={modal.mode} />
            <div className="settings-inline-actions dialog-inline-actions add-account-actions">
              <Button
                variant="primary"
                loading={!!modal.busy || !!modal.detecting}
                disabled={!!modal.busy || !!modal.detecting}
                onClick={() => {
                  setModal((current) => ({ ...current, busy: true, detecting: false, completed: false, successMessage: "" }));
                  startAddAccount(modal.mode, modal.name).catch((e) => {
                    setModal((current) => ({ ...current, busy: false }));
                    setError(e?.message || String(e));
                  });
                }}
              >
                Start
              </Button>
              <Button
                disabled={!canCopyEmail}
                disabledReason={!canCopyEmail ? "Email is not available yet. It appears after the profile is detected." : ""}
                onClick={() => copyToClipboard("Email", canCopyEmail ? emailValue : "")}
              >
                Copy email
              </Button>
              <Button
                disabled={!canCopyLoginUrl}
                disabledReason={!canCopyLoginUrl ? "Login URL is not ready yet." : ""}
                onClick={() => copyToClipboard("Login URL", canCopyLoginUrl ? loginUrlValue : "")}
              >
                Copy login URL
              </Button>
              {modal.session?.status === "running" ? (
                <Button
                  variant="warning"
                  onClick={() => cancelLoginSession(modal.session?.id).catch((e) => setError(e?.message || String(e)))}
                >
                  Cancel login
                </Button>
              ) : null}
            </div>
            {modal.session && (
              <div className="auth-session-card">
                <LabelValueRow label="Status" value={modal.session.status || "-"} />
                <LabelValueRow label="Email" value={emailValue || "-"} />
                <LabelValueRow label="Login URL" value={loginUrlValue || "-"} />
                <LabelValueRow label="Code" value={modal.session.code || "-"} />
              </div>
            )}
            {modal.detecting ? <p className="muted">Detecting and refreshing the new profile...</p> : null}
            {modal.completed && modal.successMessage ? <p className="muted"><strong>Success:</strong> {modal.successMessage}</p> : null}
          </div>
        </Dialog>
          );
        })()
      )}

      {modal?.type === "auth-relogin" && (
        (() => {
          const loginUrlValue = resolveSessionLoginUrl(modal.session, modal.mode);
          const canCopyLoginUrl = isCopyableUrl(loginUrlValue);
          return (
        <Dialog
          title={`Re-login profile - ${modal.name || "profile"}`}
          size="md"
          onClose={() => setModal(null)}
          footer={<Button onClick={() => setModal(null)}>Close</Button>}
        >
          <div className="modal-form">
            <p>Replace expired auth for this profile using your preferred login flow.</p>
            <div className="auth-session-card">
              <LabelValueRow label="Profile" value={modal.name || "-"} />
              <LabelValueRow label="Email" value={modal.email || "-"} />
            </div>
            <label>Login mode</label>
            <select
              value={modal.mode || "device"}
              disabled={!!modal.busy || modal.session?.status === "running"}
              onChange={(event) => setModal((current) => (
                current?.type === "auth-relogin"
                  ? {
                      ...current,
                      mode: event.target.value,
                      session: null,
                      busy: false,
                      detecting: false,
                      completed: false,
                      successMessage: "",
                    }
                  : current
              ))}
            >
              <option value="device">Device Login</option>
              <option value="normal">Normal Login</option>
            </select>
            <LoginModeHelp mode={modal.mode} />
            <div className="auth-session-card">
              <LabelValueRow label="Status" value={modal.session?.status || (modal.busy ? "starting" : (modal.completed ? "completed" : "-"))} />
              <LabelValueRow label="Login URL" value={loginUrlValue || "-"} />
              <LabelValueRow label="Code" value={modal.mode === "device" ? (modal.session?.code || "-") : "-"} />
            </div>
            <div className="settings-inline-actions auth-relogin-actions">
              <Button
                variant="primary"
                loading={!!modal.busy}
                disabled={!!modal.busy || modal.session?.status === "running"}
                onClick={() => {
                  setModal((current) => ({ ...current, busy: true, completed: false, successMessage: "" }));
                  startAddAccount(modal.mode || "device", modal.name, { force: true, keepDialogOnSuccess: true }).catch((e) => {
                    setModal((current) => ({ ...current, busy: false }));
                    setError(e?.message || String(e));
                  });
                }}
              >
                Start
              </Button>
              <Button onClick={() => copyToClipboard("Email", modal.email)}>
                Copy email
              </Button>
              <Button
                disabled={!canCopyLoginUrl}
                disabledReason={!canCopyLoginUrl ? "Login URL is not ready yet." : ""}
                onClick={() => copyToClipboard("Login URL", canCopyLoginUrl ? loginUrlValue : "")}
              >
                Copy login URL
              </Button>
              {modal.mode === "device" && modal.session?.status === "running" ? (
                <Button
                  variant="warning"
                  onClick={() => cancelLoginSession(modal.session?.id).catch((e) => setError(e?.message || String(e)))}
                >
                  Cancel login
                </Button>
              ) : null}
            </div>
            {modal.session?.error ? <p className="workspace-error">{modal.session.error}</p> : null}
            {modal.completed && modal.successMessage ? <p className="muted"><strong>Success:</strong> {modal.successMessage}</p> : null}
          </div>
        </Dialog>
          );
        })()
      )}

      <input
        ref={fileInputRef}
        className="hidden-file-input"
        type="file"
        accept=".camzip,application/zip"
        onChange={(event) => {
          const file = event.target.files?.[0] || null;
          if (file) {
            openImportAnalyzeStep(file);
          }
          event.target.value = "";
        }}
      />

      {modal?.type === "export" && (() => {
        const fallbackRows = buildProfileRows(state).map((row) => ({
          name: String(row?.name || "").trim(),
          email: String(row?.email_display || row?.email || "").trim() || "-",
        }));
        const sourceRows = Array.isArray(modal.rows) && modal.rows.length ? modal.rows : fallbackRows;
        const rowMap = new Map();
        sourceRows.forEach((row) => {
          const name = String(row?.name || "").trim();
          if (!name || rowMap.has(name)) return;
          rowMap.set(name, {
            name,
            email: String(row?.email || row?.email_display || "").trim() || "-",
          });
        });
        const availableRows = Array.from(rowMap.values());
        const availableNames = availableRows.map((row) => row.name);
        const selectedNames = ensureUniqueNames(modal.selected || []).filter((name) => availableNames.includes(name));
        const allSelected = availableNames.length > 0 && selectedNames.length === availableNames.length;
        const exporting = !!modal.exporting;
        return (
          <Dialog
            title="Export profiles"
            size="lg"
            onClose={() => setModal(null)}
            footer={(
              <Button
                variant="primary"
                loading={exporting}
                disabled={selectedNames.length < 1 || exporting}
                disabledReason="Select at least one profile to export."
                onClick={() => {
                  setModal((current) => {
                    if (!current || current.type !== "export") return current;
                    return { ...current, exporting: true };
                  });
                  handleExportProfiles(selectedNames, modal.filename || "profiles")
                    .catch((e) => {
                      setModal((current) => {
                        if (!current || current.type !== "export") return current;
                        return { ...current, exporting: false };
                      });
                      setError(e?.message || String(e));
                    });
                }}
              >
                Export selected
              </Button>
            )}
          >
            <div className="modal-form">
              <label>Archive name</label>
              <input value={modal.filename} onChange={(event) => setModal((current) => ({ ...current, filename: event.target.value }))} />
              <div className="modal-selection-toolbar">
                <label className="modal-check modal-check-inline">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={(event) => setModal((current) => {
                      if (!current || current.type !== "export") return current;
                      return { ...current, selected: event.target.checked ? [...availableNames] : [] };
                    })}
                  />
                  <span>Select all</span>
                </label>
                <div className="settings-inline-actions">
                  <Button onClick={() => setModal((current) => (current && current.type === "export" ? { ...current, selected: [...availableNames] } : current))}>Select all</Button>
                  <Button onClick={() => setModal((current) => (current && current.type === "export" ? { ...current, selected: [] } : current))}>Unselect all</Button>
                </div>
              </div>
              <p className="modal-summary-text">{selectedNames.length} of {availableNames.length} selected</p>
              <div className="modal-check-list export-profile-grid">
                {availableRows.map((row) => (
                  <label key={row.name} className="export-profile-card">
                    <input
                      type="checkbox"
                      checked={selectedNames.includes(row.name)}
                      onChange={(event) => setModal((current) => {
                        if (!current || current.type !== "export") return current;
                        const next = new Set(current.selected || []);
                        if (event.target.checked) next.add(row.name);
                        else next.delete(row.name);
                        return { ...current, selected: Array.from(next) };
                      })}
                    />
                    <span className="export-profile-meta">
                      <strong className="export-profile-name">{row.name}</strong>
                      <span className="export-profile-email">{row.email}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </Dialog>
        );
      })()}

      {modal?.type === "import-warning-choose" && (
        <Dialog
          title="Import profiles"
          size="sm"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={() => setModal(null)}>Cancel</Button>
              <Button
                variant="warning"
                onClick={() => {
                  setModal(null);
                  triggerImportArchivePicker();
                }}
              >
                Choose archive
              </Button>
            </>
          )}
        >
          <p>Imported data may grant account access and should only come from a trusted source. Keep exported files private, do not share them with other people, and use this feature at your own risk.</p>
        </Dialog>
      )}

      {modal?.type === "import-warning-analyze" && (
        <Dialog
          title="Import profiles"
          size="sm"
          onClose={() => setModal(null)}
          footer={(
            <>
              <Button onClick={() => setModal(null)}>Cancel</Button>
              <Button
                variant="warning"
                loading={!!modal.busy}
                onClick={() => importAnalyze(modal.file).catch((err) => setError(err?.message || String(err)))}
              >
                Analyze import
              </Button>
            </>
          )}
        >
          <p>Selected file: <strong>{modal.file?.name || "archive"}</strong></p>
          <p>Imported data may grant account access and should only come from a trusted source. Continue and analyze this archive?</p>
        </Dialog>
      )}

      {modal?.type === "import-review" && (() => {
        const rows = cloneImportPlanRows(modal.profiles || []);
        const summary = buildImportPlanSummary(rows);
        const applyDisabledReason = summary.invalidRenameCount > 0
          ? "Set a new profile name for each Rename action."
          : summary.selectedCount < 1
            ? "Select at least one profile action other than Skip."
            : "";
        return (
          <Dialog
            title="Import review"
            size="lg"
            onClose={() => setModal(null)}
            footer={(
              <Button
                variant="primary"
                disabled={!!applyDisabledReason}
                disabledReason={applyDisabledReason}
                onClick={() => applyImport(modal.analysis, rows).catch((e) => setError(e?.message || String(e)))}
              >
                Apply import
              </Button>
            )}
          >
            <div className="modal-form">
              <LabelValueRow label="Archive" value={modal.file?.name || "uploaded file"} />
              <p className="modal-summary-text">Profiles in archive: {summary.total}. Selected for apply: {summary.selectedCount}. Overwrite actions: {summary.overwriteCount}.</p>
              <div className="import-review-list">
                {rows.map((row) => {
                  const actionValue = normalizeImportPlanAction(row);
                  return (
                    <div key={row.name} className="import-review-item">
                      <div className="import-review-head">
                        <div className="import-review-name-wrap">
                          <strong>{row.name || "-"}</strong>
                          <span className="muted">{row.account_hint || "-"}</span>
                        </div>
                        <Badge variant={importStatusVariant(row.status)}>{String(row.status || "unknown").replaceAll("_", " ")}</Badge>
                      </div>
                      {Array.isArray(row.problems) && row.problems.length ? (
                        <ul className="import-review-problems">
                          {row.problems.map((problem, index) => <li key={`${row.name}-p-${index}`}>{problem}</li>)}
                        </ul>
                      ) : null}
                      <div className="import-review-actions">
                        <select
                          value={actionValue}
                          onChange={(event) => updateImportPlanRow(row.name, { action: event.target.value })}
                        >
                          <option value="import">Import</option>
                          <option value="skip">Skip</option>
                          <option value="rename">Rename</option>
                          <option value="overwrite" disabled={!row.existing_name}>Overwrite</option>
                        </select>
                        {actionValue === "rename" ? (
                          <input
                            value={String(row.rename_to || "")}
                            placeholder="new profile name"
                            onChange={(event) => updateImportPlanRow(row.name, { rename_to: event.target.value })}
                          />
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Dialog>
        );
      })()}

      {modal?.type === "import-review-confirm" && (
        <Dialog
          title="Confirm import apply"
          size="sm"
          onClose={() => setModal({ ...modal, type: "import-review" })}
          footer={(
            <>
              <Button onClick={() => setModal({ ...modal, type: "import-review" })}>Back</Button>
              <Button
                variant="danger"
                onClick={() => applyImport(modal.analysis, modal.profiles || [], { skipRiskConfirm: true }).catch((e) => setError(e?.message || String(e)))}
              >
                Apply import
              </Button>
            </>
          )}
        >
          <p>One or more profiles will overwrite existing saved profiles. Keep exported data private and only import from a trusted source.</p>
          <p>Apply this import now?</p>
        </Dialog>
      )}

      {modal?.type === "chain-edit" && (
        <Dialog
          title="Edit switch chain"
          size="lg"
          onClose={() => setModal(null)}
          footer={(
            <Button
              variant="primary"
              onClick={() => {
                const payloadChain = ensureLockedChainOrder(modal.chain || [], modal.lockedName || "");
                request("/api/auto-switch/chain", {
                  method: "POST",
                  body: JSON.stringify({ chain: payloadChain }),
                })
                  .then((nextChain) => {
                    setAutoChain(normalizeChainPayload(nextChain));
                    return loadAll();
                  })
                  .catch((e) => setError(e?.message || String(e)));
                setModal(null);
              }}
            >
              Save
            </Button>
          )}
        >
          <div className="chain-edit-hint">Drag rows to set switch order. Active account stays locked at the top.</div>
          <div className="chain-edit-list" data-testid="chain-edit-list">
            {(modal.chain || []).length ? (modal.chain || []).map((name, index) => {
              const isLocked = !!modal.lockedName && name === modal.lockedName;
              const metrics = chainMetricsByName.get(name) || { usage5: null, usageWeekly: null };
              return (
                <React.Fragment key={name}>
                  <div
                    className={`chain-edit-item ${isLocked ? "locked" : ""}`}
                    draggable={!isLocked}
                    onDragStart={(event) => {
                      if (isLocked) {
                        event.preventDefault();
                        return;
                      }
                      if (event.dataTransfer) {
                        event.dataTransfer.setData("text/plain", String(index));
                        event.dataTransfer.effectAllowed = "move";
                      }
                      event.currentTarget.classList.add("dragging");
                    }}
                    onDragEnd={(event) => {
                      event.currentTarget.classList.remove("dragging");
                    }}
                    onDragOver={(event) => {
                      if (isLocked) {
                        return;
                      }
                      event.preventDefault();
                      if (event.dataTransfer) {
                        event.dataTransfer.dropEffect = "move";
                      }
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      const from = Number(event.dataTransfer?.getData("text/plain"));
                      const to = index;
                      if (!Number.isInteger(from) || !Number.isInteger(to) || from === to) {
                        return;
                      }
                      if (from === 0 || to === 0) {
                        return;
                      }
                      setModal((current) => {
                        if (!current || current.type !== "chain-edit") {
                          return current;
                        }
                        const next = [...(current.chain || [])];
                        const [moved] = next.splice(from, 1);
                        next.splice(to, 0, moved);
                        return {
                          ...current,
                          chain: ensureLockedChainOrder(next, current.lockedName || ""),
                        };
                      });
                    }}
                  >
                    <div className="chain-edit-main">
                      <div className="chain-edit-name">{name}</div>
                      <div className="chain-edit-meta">{isLocked ? "Active account (fixed)" : `Position ${index + 1}`}</div>
                      <div className="chain-edit-metrics">
                        <span className={["chain-edit-metric", progressToneClass(metrics.usage5)].filter(Boolean).join(" ")}>5H {formatPctValue(metrics.usage5)}</span>
                        <span className={["chain-edit-metric", progressToneClass(metrics.usageWeekly)].filter(Boolean).join(" ")}>W {formatPctValue(metrics.usageWeekly)}</span>
                      </div>
                    </div>
                    <div className="chain-edit-handle">{isLocked ? "Locked" : "Drag"}</div>
                  </div>
                  {index < (modal.chain || []).length - 1 ? <div className="chain-edit-arrow" aria-hidden="true">↓</div> : null}
                </React.Fragment>
              );
            }) : <div className="chain-edit-empty">No profiles available.</div>}
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
