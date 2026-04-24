const token = __TOKEN_JSON__;
const UI_VERSION = __UI_VERSION_JSON__;
let currentRefreshTimer = null;
let allRefreshTimer = null;
let remainTicker = null;
let autoSwitchStateTimer = null;
let eventsTimer = null;
let sortState = JSON.parse(localStorage.getItem("codex_sort_state") || '{"key":"savedAt","dir":"desc"}');
let latestData = { status: null, usage: null, list: null, config: null, autoState: null, autoChain: null, events: [] };
let sessionUsageCache = null;
let usageFlashUntil = {};
let usageFetchBlinkActive = false;
let lastEventId = 0;
const notifiedEventIds = new Set();
let alarmAudioCtx = null;
let notificationSwRegistration = null;
let baseLogs = [];
let overlayLogs = [];
let activeRowActionsName = null;
let addDeviceSessionId = null;
let addDevicePollTimer = null;
let addDeviceSessionState = null;
let addDeviceProfileName = "";
let chainEditNames = [];
let chainEditLockedName = "";
let autoSwitchTimingSaveTimer = null;
let autoSwitchPolicySaveTimer = null;
let configSaveQueue = Promise.resolve();
let pendingConfigSaves = 0;
let latestConfigRevision = null;
let saveUiVisibleSince = 0;
let saveUiHideTimer = null;
let pendingAutoSwitchEnabled = null;
let switchInFlight = false;
let switchPendingName = "";
let autoSwitchRunActionInFlight = false;
let autoSwitchRapidActionInFlight = false;
let suppressCurrentProfileAutoAnimation = false;
let refreshRunning = false;
let refreshQueuedOpts = null;
let currentRefreshRunning = false;
let allRefreshSweepRunning = false;
let guideReleaseLoaded = false;
let guideReleaseLoading = false;
let guideReleaseLastPayload = null;
let appUpdateState = null;
let appUpdateInFlight = false;
let appUpdateRequestController = null;
let appUpdateProgressTimer = null;
let appUpdateProgressValue = 0;
let appUpdateProgressLabel = "";
let appUpdateProgressNote = "";
let appUpdateOutputLines = [];
let diagnosticsHooksInstalled = false;
let exportSelectedNames = [];
let importReviewState = null;
const DEFAULT_NOTIFICATION_TONES = [
  { t: 0.0, f: 880, d: 0.22, g: 0.18 },
  { t: 0.28, f: 1046, d: 0.22, g: 0.18 },
  { t: 0.56, f: 1318, d: 0.34, g: 0.2 },
];
const MAX_OVERLAY_LOGS = 900;
const LOG_COALESCE_WINDOW_MS = 3500;
const LOG_STRING_LIMIT = 360;
const LOG_DETAIL_LIMIT = 1200;
const POLL_PATHS = new Set([
  "/api/status",
  "/api/ui-config",
  "/api/auto-switch/state",
  "/api/events",
  "/api/debug/logs",
  "/api/list",
  "/api/usage-local",
  "/api/usage-local/current",
  "/api/usage-local/profile",
]);
let activeModalResolver = null;
const columnLabels = { cur:"STS", profile:"Profile", email:"Email", h5:"5H Usage", h5remain:"5H Remain", h5reset:"5H Reset At", weekly:"Weekly", weeklyremain:"W Remain", weeklyreset:"Weekly Reset At", plan:"Plan", paid:"Paid", id:"ID", added:"Added", note:"Note", auto:"Auto", actions:"Actions" };
const defaultColumns = { cur:true, profile:true, email:true, h5:true, h5remain:true, h5reset:false, weekly:true, weeklyremain:true, weeklyreset:false, plan:false, paid:false, id:false, added:false, note:false, auto:false, actions:true };
const requiredColumns = new Set(["h5remain", "weeklyremain"]);
function normalizeColumnPrefs(pref){
  const next = { ...defaultColumns, ...(pref || {}) };
  requiredColumns.forEach((k) => { next[k] = true; });
  return next;
}
function isLegacyAllColumnsEnabled(pref){
  try { return Object.keys(defaultColumns).every((k) => !!pref[k]); } catch(_) { return false; }
}
let columnPrefs = (() => {
  try {
    const p = JSON.parse(localStorage.getItem("codex_table_columns") || "{}") || {};
    const migrated = localStorage.getItem("codex_table_columns_default_v2") === "1";
    if(!migrated && p && Object.keys(p).length && isLegacyAllColumnsEnabled(p)){
      localStorage.setItem("codex_table_columns_default_v2", "1");
      const normalized = normalizeColumnPrefs(defaultColumns);
      localStorage.setItem("codex_table_columns", JSON.stringify(normalized));
      return normalized;
    }
    return normalizeColumnPrefs(p);
  } catch(_) { return normalizeColumnPrefs(defaultColumns); }
})();
window.__camBootState = { booted: false, lastError: null, version: UI_VERSION, ts: Date.now() };

function byId(id, required=true){ const el=document.getElementById(id); if(!el && required) throw new Error("Missing element: "+id); return el; }
function showFatal(e){ const b=byId("fatalBanner", false); if(!b) return; b.style.display="block"; b.textContent="UI boot error: " + (e?.message || String(e)); }
function setError(msg){ const e=byId("error", false); if(e) e.textContent = msg || ""; }
function showInAppNotice(title, body, opts){
  const stack = byId("inAppNoticeStack", false);
  if(!stack) return;
  const holdMs = Math.max(1500, Number((opts && opts.duration_ms) || 7000));
  const keep = !!(opts && opts.require_interaction);
  const card = document.createElement("div");
  card.className = "inapp-notice";
  card.innerHTML = `<div class="inapp-notice-title">${escHtml(title || "Notification")}</div><div class="inapp-notice-body">${escHtml(body || "")}</div>`;
  stack.prepend(card);
  while(stack.children.length > 5){
    const last = stack.lastElementChild;
    if(last) last.remove();
    else break;
  }
  if(!keep){
    setTimeout(() => { try { card.remove(); } catch(_) {} }, holdMs);
  }
}
function intOrDefault(raw, fallback, min=0, max=1000000){
  const n = parseInt(String(raw ?? "").trim(), 10);
  const base = Number.isFinite(n) ? n : Number(fallback);
  const safe = Number.isFinite(base) ? base : min;
  return Math.max(min, Math.min(max, safe));
}
function setControlValueIfPristine(id, value){
  const el = byId(id, false);
  if(!el) return;
  if(el.dataset.dirty === "1") return;
  const next = String(value ?? "");
  if(String(el.value ?? "") !== next) el.value = next;
}
function formatCountdownMMSS(secRaw){
  const sec = Math.max(0, Math.floor(Number(secRaw) || 0));
  const mm = Math.floor(sec / 60);
  const ss = sec % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
function updateAutoSwitchArmedUI(){
  const card = byId("autoSwitchRulesSection", false);
  const badge = byId("asPendingCountdown", false);
  const state = latestData?.autoState || {};
  const due = Number(state.pending_switch_due_at || 0);
  const delay = Math.max(1, Number(state.config_delay_sec || 0) || 1);
  const nowSec = Date.now() / 1000;
  const remaining = due - nowSec;
  const armed = Number.isFinite(due) && due > 0 && remaining > 0;
  const urgencyClasses = ["switch-urgency-green", "switch-urgency-yellow", "switch-urgency-orange", "switch-urgency-red"];
  let urgency = "switch-urgency-green";
  if(armed){
    const ratio = Math.max(0, Math.min(1, remaining / delay));
    if(remaining <= 3 || ratio <= 0.15) urgency = "switch-urgency-red";
    else if(remaining <= 8 || ratio <= 0.35) urgency = "switch-urgency-orange";
    else if(remaining <= 16 || ratio <= 0.6) urgency = "switch-urgency-yellow";
  }
  if(card){
    card.classList.toggle("auto-switch-armed", !!armed);
    card.classList.remove(...urgencyClasses);
    if(armed) card.classList.add(urgency);
  }
  if(!badge) return;
  if(armed){
    badge.classList.add("active");
    badge.classList.remove(...urgencyClasses);
    badge.classList.add(urgency);
    badge.textContent = `Switch in ${formatCountdownMMSS(remaining)}`;
  } else {
    badge.classList.remove("active");
    badge.classList.remove(...urgencyClasses);
    badge.textContent = "Switch in 00:00";
  }
}
function updateRankingModeUI(modeRaw, enabledRaw){
  const enabled = enabledRaw !== undefined ? !!enabledRaw : !!byId("asEnabled", false)?.checked;
  const mode = String(modeRaw || "balanced");
  const manual = mode === "manual";
  const chainPanel = byId("asChainPanel", false);
  const autoArrangeRow = byId("asAutoArrangeRow", false);
  const chainEditBtn = byId("asChainEditBtn", false);
  if(chainPanel) chainPanel.style.display = enabled ? "" : "none";
  if(autoArrangeRow) autoArrangeRow.style.display = enabled ? "" : "none";
  if(chainEditBtn){
    chainEditBtn.disabled = !enabled;
    chainEditBtn.title = enabled ? (manual ? "Edit manual chain order" : "Edit chain (switches ranking to manual)") : "Enable auto-switch first";
  }
}
function setConfigSavingState(active, text){
  if(saveUiHideTimer){
    clearTimeout(saveUiHideTimer);
    saveUiHideTimer = null;
  }
  const spinner = byId("saveSpinner", false);
  if(active){
    saveUiVisibleSince = Date.now();
    if(spinner) spinner.classList.add("active");
  } else {
    const elapsed = Date.now() - saveUiVisibleSince;
    const remain = Math.max(0, 220 - elapsed);
    const hideNow = () => {
      if(spinner) spinner.classList.remove("active");
    };
    if(remain > 0){
      saveUiHideTimer = setTimeout(hideNow, remain);
    } else {
      hideNow();
    }
  }
}
async function enqueueConfigPatch(patch){
  pendingConfigSaves += 1;
  setConfigSavingState(true, "Saving...");
  const applyPatch = async () => {
    const keys = Object.keys(patch || {});
    const payload = { ...(patch || {}) };
    if(Number.isFinite(Number(latestConfigRevision))){
      payload.base_revision = Number(latestConfigRevision);
    }
    pushOverlayLog("ui", "config.patch", { keys, base_revision: payload.base_revision || null });
    try{
      const cfg = await postApi("/api/ui-config", payload);
      latestConfigRevision = Number(cfg?._meta?.revision || latestConfigRevision || 1);
      return cfg;
    } catch(e){
      const msg = String(e?.message || "");
      if(msg.includes("Config changed elsewhere")){
        await refreshAll({ usageTimeoutSec: 2 });
        const retryPayload = { ...(patch || {}) };
        if(Number.isFinite(Number(latestConfigRevision))){
          retryPayload.base_revision = Number(latestConfigRevision);
        }
        const cfg2 = await postApi("/api/ui-config", retryPayload);
        latestConfigRevision = Number(cfg2?._meta?.revision || latestConfigRevision || 1);
        return cfg2;
      }
      throw e;
    }
  };
  const run = configSaveQueue.then(applyPatch);
  configSaveQueue = run.catch(() => {});
  try{
    return await run;
  } finally {
    pendingConfigSaves = Math.max(0, pendingConfigSaves - 1);
    if(pendingConfigSaves === 0) setConfigSavingState(false);
  }
}
function usageClass(v){ const n=Number(v); if(Number.isNaN(n))return ""; if(n<25)return "usage-low"; if(n<50)return "usage-midlow"; if(n<75)return "usage-mid"; return "usage-good"; }
function usageErrorLabel(rowError){
  const msg = String(rowError || "").trim();
  if(!msg) return "";
  const lower = msg.toLowerCase();
  if(lower === "http 401") return "auth expired";
  if(lower === "http 403") return "access denied";
  if(lower.startsWith("http ")) return msg;
  if(lower.includes("timed out")) return "timeout";
  if(lower.includes("missing access_token/account_id")) return "missing auth";
  return msg;
}
function fmtUsagePct(usage){
  const n = Number(usage?.remaining_percent);
  if(Number.isFinite(n)) return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
  return usage?.text || "-";
}
function usagePercentNumber(usage){
  const n = Number(usage?.remaining_percent);
  if(!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n)));
}
function usageFillClass(n){
  if(!Number.isFinite(n)) return "good";
  if(n < 25) return "low";
  if(n < 50) return "midlow";
  if(n < 75) return "mid";
  return "good";
}
function usageMetricSignature(usage){
  const pct = usagePercentNumber(usage);
  const resetTs = Number(usage?.resets_at || 0);
  const text = String(usage?.text || "");
  return `${Number.isFinite(pct) ? pct : "na"}|${Number.isFinite(resetTs) ? resetTs : "na"}|${text}`;
}
function markUsageFlashUpdates(prevUsage, nextUsage){
  if(!prevUsage || !nextUsage) return;
  const prevRows = Array.isArray(prevUsage?.profiles) ? prevUsage.profiles : [];
  const nextRows = Array.isArray(nextUsage?.profiles) ? nextUsage.profiles : [];
  if(!prevRows.length || !nextRows.length) return;
  const until = Date.now() + 1400;
  const prevByName = {};
  for(const row of prevRows){
    const name = String(row?.name || "").trim();
    if(name) prevByName[name] = row;
  }
  for(const row of nextRows){
    const name = String(row?.name || "").trim();
    if(!name) continue;
    const prev = prevByName[name];
    if(!prev) continue;
    if(usageMetricSignature(prev.usage_5h) !== usageMetricSignature(row.usage_5h)){
      usageFlashUntil[`${name}|h5`] = until;
    }
    if(usageMetricSignature(prev.usage_weekly) !== usageMetricSignature(row.usage_weekly)){
      usageFlashUntil[`${name}|weekly`] = until;
    }
  }
}
function shouldFlashUsage(name, metric){
  const key = `${String(name || "").trim()}|${metric}`;
  const until = Number(usageFlashUntil[key] || 0);
  if(!Number.isFinite(until) || until <= 0) return false;
  if(until < Date.now()){
    delete usageFlashUntil[key];
    return false;
  }
  return true;
}
function shouldBlinkUsage(name, metric, loading){
  if(loading) return false;
  return !!usageFetchBlinkActive || shouldFlashUsage(name, metric);
}
function isUsageLoadingState(usage, rowError, rowLoading){
  if(!!rowLoading) return true;
  const pct = usagePercentNumber(usage);
  if(!rowError) return false;
  const msg = String(rowError || "").toLowerCase();
  let transient = msg.includes("request failed") || msg.includes("timed out");
  if(!transient && msg.startsWith("http ")){
    const code = parseInt(msg.slice(5).trim(), 10);
    if(Number.isFinite(code)){
      // Treat only retryable HTTP statuses as loading placeholders.
      transient = (code >= 500) || code === 408 || code === 429;
    }
  }
  if(!transient) return false;
  if(!Number.isFinite(pct)) return true;
  const resetTs = Number(usage?.resets_at || 0);
  return !(Number.isFinite(resetTs) && resetTs > 0);
}
function renderUsageMeter(usage, loading=false, flash=false){
  if(loading){
    return `<div class="usage-cell usage-cell-loading"><span class="usage-pct loading-text">loading...</span><div class="usage-meter loading"><span class="usage-fill shimmer"></span></div></div>`;
  }
  const pct = usagePercentNumber(usage);
  if(!Number.isFinite(pct)){
    return "<span>-</span>";
  }
  const tone = usageFillClass(pct);
  const txtClass = usageClass(pct);
  return `<div class="usage-cell ${flash ? "updated" : ""}"><span class="usage-pct ${txtClass}">${pct}%</span><div class="usage-meter"><span class="usage-fill ${tone} ${flash ? "blink" : ""}" style="width:${pct}%"></span></div></div>`;
}
function renderUsageErrorCell(rowError){
  const label = usageErrorLabel(rowError) || "error";
  return `<div class="usage-cell"><span class="usage-pct usage-low">${escHtml(label)}</span><div class="usage-meter"><span class="usage-fill low" style="width:100%"></span></div></div>`;
}
function fmtReset(ts){ if(!ts) return "unknown"; try { const d = new Date(Number(ts)*1000); return Number.isFinite(d.getTime()) ? d.toLocaleString() : "unknown"; } catch(_) { return "unknown"; } }
function fmtSavedAt(ts){ if(!ts) return "-"; try { const d = new Date(ts); return Number.isFinite(d.getTime()) ? d.toLocaleString() : ts; } catch(_) { return ts; } }
function formatPctValue(v){
  const n = Number(v);
  return Number.isFinite(n) ? `${Math.max(0, Math.min(100, Math.round(n)))}%` : "-";
}
function renderChainPreview(payload){
  const el = byId("asChainPreview", false);
  if(!el) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if(!items.length){
    el.textContent = payload?.chain_text || "-";
    return;
  }
  const parts = [];
  for(let i=0;i<items.length;i++){
    const it = items[i] || {};
    const h5 = Number(it.remaining_5h);
    const w = Number(it.remaining_weekly);
    const h5Class = usageClass(h5);
    const wClass = usageClass(w);
    parts.push(
      `<span class="chain-node"><span class="chain-name">${escHtml(String(it.name || "-"))}</span><span class="chain-metric ${h5Class}">5H ${formatPctValue(h5)}</span><span class="chain-metric ${wClass}">W ${formatPctValue(w)}</span></span>`
    );
    if(i < items.length - 1) parts.push(`<span class="chain-arrow">-></span>`);
  }
  el.innerHTML = parts.join("");
}
function getChainEditSourceNames(){
  const payload = latestData.autoChain || {};
  const chain = Array.isArray(payload.chain) ? payload.chain : [];
  const manual = Array.isArray(payload.manual_chain) ? payload.manual_chain : [];
  const names = [];
  const seen = new Set();
  const pushName = (value) => {
    const n = String(value || "").trim();
    if(!n || seen.has(n)) return;
    seen.add(n);
    names.push(n);
  };
  chain.forEach(pushName);
  manual.forEach(pushName);
  return names;
}
function getActiveChainName(){
  const chain = Array.isArray(latestData?.autoChain?.chain) ? latestData.autoChain.chain : [];
  const first = String(chain[0] || "").trim();
  if(first) return first;
  const fallback = String(latestData?.usage?.current_profile || "").trim();
  return fallback || "";
}
function closeChainEditModal(){
  const b = byId("chainEditBackdrop", false);
  if(b) b.style.display = "none";
  chainEditNames = [];
  chainEditLockedName = "";
}
function ensureLockedChainOrder(list){
  const names = Array.isArray(list) ? list.map((x)=>String(x||"").trim()).filter(Boolean) : [];
  if(!chainEditLockedName) return names;
  const rest = names.filter((n)=>n!==chainEditLockedName);
  return [chainEditLockedName, ...rest];
}
function getChainMetricsByName(name){
  const n = String(name || "").trim();
  if(!n) return { h5: null, w: null };
  const items = Array.isArray(latestData?.autoChain?.items) ? latestData.autoChain.items : [];
  for(const it of items){
    if(String(it?.name || "").trim() === n){
      const h5 = Number(it?.remaining_5h);
      const w = Number(it?.remaining_weekly);
      return {
        h5: Number.isFinite(h5) ? h5 : null,
        w: Number.isFinite(w) ? w : null,
      };
    }
  }
  const rows = Array.isArray(latestData?.usage?.profiles) ? latestData.usage.profiles : [];
  for(const row of rows){
    if(String(row?.name || "").trim() === n){
      const h5 = Number(row?.usage_5h?.remaining_percent);
      const w = Number(row?.usage_weekly?.remaining_percent);
      return {
        h5: Number.isFinite(h5) ? h5 : null,
        w: Number.isFinite(w) ? w : null,
      };
    }
  }
  return { h5: null, w: null };
}
function renderChainEditModal(){
  const list = byId("chainEditList", false);
  if(!list) return;
  list.innerHTML = "";
  if(!chainEditNames.length){
    list.innerHTML = `<div class="chain-edit-empty">No profiles available.</div>`;
    return;
  }
  chainEditNames.forEach((name, index) => {
    const row = document.createElement("div");
    const isLocked = !!chainEditLockedName && name === chainEditLockedName;
    const metrics = getChainMetricsByName(name);
    const h5Class = usageClass(metrics.h5);
    const wClass = usageClass(metrics.w);
    const h5Text = formatPctValue(metrics.h5);
    const wText = formatPctValue(metrics.w);
    row.className = `chain-edit-item ${isLocked ? "locked" : ""}`;
    row.draggable = !isLocked;
    row.dataset.index = String(index);
    row.innerHTML = `<div class="chain-edit-main"><div class="name">${escHtml(name)}</div><div class="meta">${isLocked ? "Active account (fixed)" : `Position ${index + 1}`}</div><div class="chain-edit-metrics"><span class="chain-edit-metric ${h5Class}">5H ${h5Text}</span><span class="chain-edit-metric ${wClass}">W ${wText}</span></div></div><div class="chain-edit-handle">${isLocked ? "Locked" : "Drag"}</div>`;
    row.addEventListener("dragstart", (ev) => {
      if(isLocked){
        ev.preventDefault();
        return;
      }
      if(ev.dataTransfer){
        ev.dataTransfer.setData("text/plain", String(index));
        ev.dataTransfer.effectAllowed = "move";
      }
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      if(ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
    });
    row.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const from = Number(ev.dataTransfer?.getData("text/plain"));
      const to = Number(row.dataset.index);
      if(!Number.isInteger(from) || !Number.isInteger(to) || from === to) return;
      if(from === 0 || to === 0) return;
      const next = [...chainEditNames];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      chainEditNames = ensureLockedChainOrder(next);
      renderChainEditModal();
    });
    list.appendChild(row);
    if(index < chainEditNames.length - 1){
      const arrow = document.createElement("div");
      arrow.className = "chain-edit-arrow";
      arrow.textContent = "↓";
      list.appendChild(arrow);
    }
  });
}
function openChainEditModal(){
  chainEditNames = getChainEditSourceNames();
  chainEditLockedName = getActiveChainName();
  chainEditNames = ensureLockedChainOrder(chainEditNames);
  renderChainEditModal();
  const b = byId("chainEditBackdrop", false);
  if(b) b.style.display = "flex";
}
function fmtRemain(ts, withSeconds=false, loading=false){
  if(!ts) return loading ? "loading..." : "unknown";
  try {
    let sec = Math.max(0, Math.floor(Number(ts) - (Date.now()/1000)));
    const d = Math.floor(sec / 86400); sec %= 86400;
    const h = Math.floor(sec / 3600); sec %= 3600;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if(!withSeconds){
      if (d > 0) return `${d}d ${h}h ${m}m`;
      if (h > 0) return `${h}h ${m}m`;
      return `${m}m`;
    }
    if (d > 0) return `${d}d ${h}h ${m}m ${s}s`;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    return `${m}m ${s}s`;
  } catch(_) { return loading ? "loading..." : "unknown"; }
}
function formatRemainCell(ts, withSeconds, loading, rowError){
  if(loading) return fmtRemain(ts, withSeconds, true);
  const label = usageErrorLabel(rowError);
  if(label) return label;
  return fmtRemain(ts, withSeconds, false);
}
function refreshRemainCountdowns(){
  document.querySelectorAll("td[data-remain-ts]").forEach((el) => {
    const raw = el.getAttribute("data-remain-ts");
    const ts = Number(raw);
    const withSeconds = el.getAttribute("data-remain-seconds") === "1";
    const loading = el.getAttribute("data-remain-loading") === "1";
    el.textContent = Number.isFinite(ts) && ts > 0 ? fmtRemain(ts, withSeconds, false) : (loading ? "loading..." : "unknown");
    el.classList.toggle("loading-text", loading && !(Number.isFinite(ts) && ts > 0));
  });
  updateAutoSwitchArmedUI();
}
function themeFromPref(sel){ if(sel==="dark") return "dark"; if(sel==="light") return "light"; return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
function applyTheme(pref){ document.documentElement.setAttribute("data-theme", themeFromPref(pref || "auto")); }
function applySettingsSectionVisibility(hidden){
  document.querySelectorAll("[data-settings-section='1']").forEach((section) => {
    section.style.display = hidden ? "none" : "";
  });
  const btn = byId("settingsToggleBtn", false);
  if(btn){
    btn.setAttribute("aria-pressed", hidden ? "true" : "false");
    btn.classList.toggle("active", !hidden);
    btn.title = hidden ? "Show settings" : "Hide settings";
  }
}
function updateHeaderThemeIcon(themeValue){
  const btn = byId("themeIconBtn", false);
  if(!btn) return;
  const mode = themeValue || "auto";
  btn.classList.toggle("active", mode !== "auto");
  btn.title = `Theme: ${mode}`;
}
function updateHeaderDebugIcon(enabled){
  const btn = byId("debugIconBtn", false);
  if(!btn) return;
  btn.classList.toggle("active", !!enabled);
  btn.title = enabled ? "Debug mode: ON" : "Debug mode: OFF";
}
function shouldTraceRequest(path, method){
  const m = String(method || "GET").toUpperCase();
  if(m !== "GET") return true;
  return !POLL_PATHS.has(String(path || ""));
}
function getMergedLogs(limit=1200){
  const merged = [...baseLogs, ...overlayLogs].map((r) => ({
    ts: r.ts || new Date().toISOString(),
    last_ts: r.last_ts || null,
    repeat_count: Number(r.repeat_count || 1),
    level: String(r.level || "info").toLowerCase(),
    message: String(r.message || ""),
    details: r.details || null,
  }));
  if(limit > 0 && merged.length > limit) return merged.slice(-limit);
  return merged;
}
function safeJsonStringify(value){
  try { return JSON.stringify(value); } catch(_) { return String(value); }
}
function truncateText(s, maxLen=LOG_STRING_LIMIT){
  const str = String(s ?? "");
  if(str.length <= maxLen) return str;
  return `${str.slice(0, maxLen)}… [truncated ${str.length - maxLen} chars]`;
}
function sanitizeLogDetails(value, depth=0){
  if(value === null || value === undefined) return value;
  if(typeof value === "string") return truncateText(value);
  if(typeof value === "number" || typeof value === "boolean") return value;
  if(depth > 3) return "[depth-limit]";
  if(Array.isArray(value)){
    return value.slice(0, 20).map((v) => sanitizeLogDetails(v, depth + 1));
  }
  if(typeof value === "object"){
    const out = {};
    let count = 0;
    for(const [k, v] of Object.entries(value)){
      if(count >= 24){ out.__truncated__ = "object keys truncated"; break; }
      out[k] = sanitizeLogDetails(v, depth + 1);
      count += 1;
    }
    return out;
  }
  return truncateText(String(value));
}
function compactDetailString(details){
  const raw = safeJsonStringify(details || {});
  return raw.length > LOG_DETAIL_LIMIT ? `${raw.slice(0, LOG_DETAIL_LIMIT)}… [truncated ${raw.length - LOG_DETAIL_LIMIT} chars]` : raw;
}
function installDiagnosticsHooks(){
  if(diagnosticsHooksInstalled) return;
  diagnosticsHooksInstalled = true;
  window.addEventListener("error", (ev) => {
    const err = ev?.error;
    pushOverlayLog("error", "window.error", {
      message: err?.message || ev?.message || "unknown error",
      source: ev?.filename || null,
      line: ev?.lineno || null,
      column: ev?.colno || null,
      stack: err?.stack || null,
    });
  });
  window.addEventListener("unhandledrejection", (ev) => {
    const reason = ev?.reason;
    pushOverlayLog("error", "window.unhandledrejection", {
      reason: reason?.message || String(reason || "unknown rejection"),
      stack: reason?.stack || null,
    });
  });
}

async function callApi(path, options={}){
  const method = String(options?.method || "GET").toUpperCase();
  const startedAt = Date.now();
  const shouldTrace = shouldTraceRequest(path, method);
  const timeoutMsRaw = Number(options?.timeoutMs || 0);
  const timeoutMs = Number.isFinite(timeoutMsRaw) ? Math.max(0, Math.floor(timeoutMsRaw)) : 0;
  if(shouldTrace) pushOverlayLog("ui", `api.request ${method} ${path}`);
  let res;
  let timeoutHandle = null;
  let timeoutController = null;
  const fetchOptions = { ...options };
  delete fetchOptions.timeoutMs;
  if(timeoutMs > 0){
    timeoutController = new AbortController();
    const callerSignal = options?.signal || null;
    if(callerSignal){
      if(callerSignal.aborted){
        timeoutController.abort();
      } else {
        callerSignal.addEventListener("abort", () => timeoutController && timeoutController.abort(), { once: true });
      }
    }
    fetchOptions.signal = timeoutController.signal;
    timeoutHandle = setTimeout(() => {
      try { timeoutController && timeoutController.abort(); } catch(_) {}
    }, timeoutMs);
  }
  try {
    res = await fetch(path, fetchOptions);
  } catch(e){
    if(timeoutHandle) clearTimeout(timeoutHandle);
    if(e && e.name === "AbortError"){
      if(timeoutMs > 0){
        throw new Error(`timeout after ${Math.round(timeoutMs/1000)}s`);
      }
      throw e;
    }
    pushOverlayLog("error", `api.network ${method} ${path}`, {
      error: e?.message || String(e),
      duration_ms: Date.now() - startedAt,
    });
    throw e;
  }
  if(timeoutHandle) clearTimeout(timeoutHandle);
  const body = await res.json().catch(() => ({ok:false,error:{message:"bad json"}}));
  if(!res.ok || !body.ok){
    const code = body?.error?.code || "";
    const type = body?.error?.type || "";
    const msg = body?.error?.message || "request failed";
    pushOverlayLog("error", `api.error ${method} ${path}`, {
      status: res.status,
      code: code || null,
      type: type || null,
      message: msg,
      duration_ms: Date.now() - startedAt,
    });
    if(code === "STALE_CONFIG"){
      throw new Error("Config changed elsewhere. Refreshing and retrying...");
    }
    if(code === "FORBIDDEN" && /invalid session token/i.test(msg)){
      setError("Session expired after service restart. Reloading panel...");
      setTimeout(() => { try { window.location.href = "/?r="+Date.now(); } catch(_) {} }, 350);
    }
    throw new Error(msg);
  }
  if(shouldTrace){
    pushOverlayLog("ui", `api.response ${method} ${path}`, {
      status: res.status,
      request_id: body?.meta?.request_id || null,
      duration_ms: Date.now() - startedAt,
    });
  }
  return body.data;
}
async function postApi(path, payload={}, options={}){
  return callApi(path, {
    ...options,
    method:"POST",
    headers:{"Content-Type":"application/json","X-Codex-Token":token, ...(options?.headers || {})},
    body: JSON.stringify(payload),
  });
}
async function safeGet(path, options={}){
  try { return await callApi(path, options); }
  catch(e){
    if(e && e.name === "AbortError") return { __aborted: true, __error: "request aborted" };
    return {__error:e.message};
  }
}

function escHtml(s){
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
function escAttr(s){
  return escHtml(s).replaceAll('"', "&quot;");
}
function normalizeReleaseTag(raw){
  let s = String(raw || "").trim().toLowerCase();
  if(s.startsWith("release ")) s = s.slice("release ".length);
  if(s.startsWith("v")) s = s.slice(1);
  return s.replace(/[^0-9a-z.+_-]/g, "");
}
function isCurrentReleaseTag(raw){
  const a = normalizeReleaseTag(raw);
  const b = normalizeReleaseTag(UI_VERSION);
  return !!a && !!b && a === b;
}
function formatReleaseAge(iso){
  const t = Date.parse(String(iso || ""));
  if(!Number.isFinite(t)) return "Unknown date";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if(sec < 60) return `${sec}s ago`;
  if(sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if(sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  if(sec < 86400 * 30) return `${Math.floor(sec / 86400)}d ago`;
  return new Date(t).toLocaleDateString();
}
function setGuideReleaseStatus(text, state){
  const el = byId("guideReleaseStatus", false);
  if(!el) return;
  el.textContent = String(text || "");
  el.classList.remove("synced", "fallback", "failed");
  if(state && (state === "synced" || state === "fallback" || state === "failed")){
    el.classList.add(state);
  }
}
function renderGuideReleaseNotes(payload){
  const list = byId("guideReleaseList", false);
  if(!list) return;
  const releases = Array.isArray(payload?.releases) ? payload.releases : [];
  if(!releases.length){
    list.innerHTML = `<div class="guide-release-empty">No release entries available.</div>`;
    return;
  }
  const html = releases.map((r) => {
    const tag = String(r?.tag || r?.version || "-");
    const pre = !!r?.is_prerelease;
    const current = !!r?.is_current || isCurrentReleaseTag(tag);
    const highlights = Array.isArray(r?.highlights) ? r.highlights.filter(Boolean).slice(0, 4) : [];
    const link = String(r?.url || "").trim();
    const meta = r?.published_at ? formatReleaseAge(r.published_at) : "Local entry";
    const badges = [
      pre ? `<span class="guide-release-badge prerelease">Pre-release</span>` : "",
      current ? `<span class="guide-release-badge current">Current</span>` : "",
    ].filter(Boolean).join("");
    const highlightHtml = highlights.length
      ? `<ul class="guide-release-highlights">${highlights.map((h) => `<li>${escHtml(h)}</li>`).join("")}</ul>`
      : "";
    const linkHtml = link ? `<a class="guide-release-link" href="${escAttr(link)}" target="_blank" rel="noopener noreferrer">Open on GitHub</a>` : "";
    return `
      <article class="guide-release-item ${current ? "current" : ""}">
        <div class="guide-release-row">
          <span class="guide-release-tag">${escHtml(tag)}</span>
          ${badges}
        </div>
        <div class="guide-release-meta">${escHtml(meta)}</div>
        ${highlightHtml}
        ${linkHtml}
      </article>
    `;
  }).join("");
  list.innerHTML = html;
}
async function loadGuideReleaseNotes(force=false){
  if(guideReleaseLoading) return;
  guideReleaseLoading = true;
  setGuideReleaseStatus("Loading release notes...", "");
  try{
    const path = force ? "/api/release-notes?force=true" : "/api/release-notes";
    const payload = await safeGet(path);
    if(payload.__error){
      guideReleaseLastPayload = null;
      setGuideReleaseStatus("Failed to load release notes", "failed");
      const list = byId("guideReleaseList", false);
      if(list){
        list.innerHTML = `<div class="guide-release-empty">${escHtml(payload.__error)}</div>`;
      }
      return;
    }
    guideReleaseLoaded = true;
    guideReleaseLastPayload = payload;
    const statusText = payload?.status_text || "Release notes";
    const status = String(payload?.status || "");
    setGuideReleaseStatus(statusText, status);
    renderGuideReleaseNotes(payload);
  } finally {
    guideReleaseLoading = false;
  }
}
function renderUpdateReleaseModal(state){
  const intro = byId("appUpdateIntro", false);
  const releaseEl = byId("appUpdateRelease", false);
  const outputEl = byId("appUpdateOutput", false);
  const confirmBtn = byId("appUpdateConfirmBtn", false);
  const cancelBtn = byId("appUpdateCancelBtn", false);
  const progressEl = byId("appUpdateProgress", false);
  const progressBar = byId("appUpdateProgressBar", false);
  const progressValueEl = byId("appUpdateProgressValue", false);
  const progressLabelEl = byId("appUpdateProgressLabel", false);
  const progressNoteEl = byId("appUpdateProgressNote", false);
  const release = state?.latest_release || null;
  const latestVersion = String(state?.latest_version || "");
  if(outputEl){
    const text = appUpdateOutputLines.join("\\n");
    outputEl.style.display = text ? "block" : "none";
    outputEl.textContent = text;
  }
  if(intro){
    intro.textContent = latestVersion
      ? `Review the ${latestVersion} release notes before upgrading this app with pipx.`
      : "Review the latest release notes before upgrading this app.";
  }
  if(progressEl){
    progressEl.classList.toggle("active", !!appUpdateInFlight || appUpdateProgressValue > 0);
  }
  if(progressBar){
    progressBar.style.width = `${Math.max(0, Math.min(100, Math.round(appUpdateProgressValue || 0)))}%`;
  }
  if(progressValueEl){
    progressValueEl.textContent = `${Math.max(0, Math.min(100, Math.round(appUpdateProgressValue || 0)))}%`;
  }
  if(progressLabelEl){
    progressLabelEl.textContent = appUpdateProgressLabel || (appUpdateInFlight ? "Updating..." : "Ready to update");
  }
  if(progressNoteEl){
    progressNoteEl.textContent = appUpdateProgressNote || "The update can continue in the background if you close this dialog.";
  }
  if(confirmBtn){
    confirmBtn.disabled = !state?.update_available || appUpdateInFlight;
    confirmBtn.textContent = appUpdateInFlight ? "Updating..." : "Update Now";
    confirmBtn.classList.toggle("btn-progress", !!appUpdateInFlight);
  }
  if(cancelBtn){
    cancelBtn.textContent = appUpdateInFlight ? "Close" : "Cancel";
    cancelBtn.title = appUpdateInFlight
      ? "Close this dialog while the update continues in the background."
      : "Close this update review without running the pipx upgrade.";
  }
  if(!releaseEl) return;
  if(!release){
    releaseEl.innerHTML = `<div class="update-modal-card"><div class="update-modal-body">Release notes are unavailable right now. You can still continue with the pipx upgrade if you want.</div></div>`;
    return;
  }
  const highlights = Array.isArray(release?.highlights) ? release.highlights.filter(Boolean) : [];
  const body = String(release?.body || "").trim();
  const link = String(release?.url || "").trim();
  const dateText = release?.published_at ? formatReleaseAge(release.published_at) : "Release date unavailable";
  const highlightHtml = highlights.length
    ? `<ul class="update-modal-highlights">${highlights.map((item) => `<li>${escHtml(item)}</li>`).join("")}</ul>`
    : "";
  const bodyHtml = body ? `<p class="update-modal-body">${escHtml(body)}</p>` : `<p class="update-modal-body">No release notes body was provided for this release.</p>`;
  const linkHtml = link ? `<a class="update-modal-link" href="${escAttr(link)}" target="_blank" rel="noopener noreferrer">Open on GitHub</a>` : "";
  releaseEl.innerHTML = `
    <div class="update-modal-card">
      <div class="update-modal-meta">
        <span class="update-modal-tag">${escHtml(String(release?.tag || release?.version || latestVersion || "Latest release"))}</span>
        <span class="update-modal-date">${escHtml(dateText)}</span>
      </div>
      <div class="update-modal-title">${escHtml(String(release?.title || release?.tag || latestVersion || "Latest release"))}</div>
      ${highlightHtml}
      ${bodyHtml}
      ${linkHtml}
    </div>
  `;
}
function openUpdateModal(){
  renderUpdateReleaseModal(appUpdateState || {});
  const b = byId("appUpdateBackdrop", false);
  if(b) b.style.display = "flex";
}
function closeUpdateModal(){
  const b = byId("appUpdateBackdrop", false);
  if(b) b.style.display = "none";
  if(appUpdateInFlight){
    showInAppNotice("Update Running", "The update is still running in the background. The panel will restart when it finishes.", { duration_ms: 7000 });
  }
}
function setAppUpdateProgress(value, label="", note=""){
  appUpdateProgressValue = Math.max(0, Math.min(100, Number(value) || 0));
  if(label) appUpdateProgressLabel = String(label);
  if(note !== undefined && note !== null && String(note) !== "") appUpdateProgressNote = String(note);
  renderUpdateReleaseModal(appUpdateState || {});
}
function resetAppUpdateProgress(){
  if(appUpdateProgressTimer){
    clearInterval(appUpdateProgressTimer);
    appUpdateProgressTimer = null;
  }
  appUpdateProgressValue = 0;
  appUpdateProgressLabel = "";
  appUpdateProgressNote = "";
}
function startAppUpdateProgress(){
  resetAppUpdateProgress();
  setAppUpdateProgress(8, "Preparing update request...", "Starting the local updater command.");
  appUpdateProgressTimer = setInterval(() => {
    if(!appUpdateInFlight) return;
    const next = appUpdateProgressValue < 28 ? appUpdateProgressValue + 5
      : appUpdateProgressValue < 58 ? appUpdateProgressValue + 3
      : appUpdateProgressValue < 86 ? appUpdateProgressValue + 1.5
      : appUpdateProgressValue;
    if(next !== appUpdateProgressValue){
      appUpdateProgressValue = Math.min(90, next);
      renderUpdateReleaseModal(appUpdateState || {});
    }
  }, 850);
}
function pushAppUpdateOutput(line){
  const text = String(line || "").trim();
  if(!text) return;
  appUpdateOutputLines.push(text);
  if(appUpdateOutputLines.length > 14){
    appUpdateOutputLines = appUpdateOutputLines.slice(-14);
  }
  renderUpdateReleaseModal(appUpdateState || {});
}
function summarizeUpdateOutput(raw){
  return String(raw || "")
    .split(/\\r?\\n/)
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .filter((line) => /Processing |Preparing metadata|Building wheel|Created wheel|Installing collected packages|Attempting uninstall|Successfully uninstalled|Successfully installed|error[: ]/i.test(line))
    .slice(0, 8);
}
function applyAppUpdateStatus(state){
  appUpdateState = state && typeof state === "object" ? state : {};
  const badge = byId("appUpdateBadge", false);
  const btn = byId("appUpdateBtn", false);
  const latestVersion = String(appUpdateState?.latest_version || "").trim();
  const updateAvailable = !!appUpdateState?.update_available;
  if(badge){
    badge.textContent = latestVersion ? `Update available: ${latestVersion}` : "Update available";
    badge.classList.toggle("active", updateAvailable);
  }
  if(btn){
    btn.style.display = updateAvailable ? "" : "none";
    btn.disabled = !updateAvailable || appUpdateInFlight;
    btn.textContent = appUpdateInFlight ? "Updating..." : "Update";
    btn.classList.toggle("btn-progress", !!appUpdateInFlight);
  }
}
async function loadAppUpdateStatus(force=false){
  const path = force ? "/api/app-update-status?force=true" : "/api/app-update-status";
  const payload = await safeGet(path);
  if(payload.__error){
    pushOverlayLog("warn", "app_update.status_failed", { error: payload.__error });
    applyAppUpdateStatus({
      ...(appUpdateState || {}),
      status: "failed",
      error: payload.__error,
      update_available: false,
    });
    return;
  }
  applyAppUpdateStatus(payload);
}
async function runAppUpdateFlow(){
  if(appUpdateInFlight) return;
  appUpdateInFlight = true;
  appUpdateRequestController = new AbortController();
  appUpdateOutputLines = [];
  startAppUpdateProgress();
  pushAppUpdateOutput("[1/4] Opening updater...");
  applyAppUpdateStatus(appUpdateState || {});
  renderUpdateReleaseModal(appUpdateState || {});
  setError("");
  try{
    setAppUpdateProgress(18, "Sending update command...", "Request accepted. Waiting for the upgrader to finish.");
    pushAppUpdateOutput("[2/4] Running pipx upgrade...");
    const data = await postApi("/api/system/update", {}, { signal: appUpdateRequestController.signal, timeoutMs: 180000 });
    setAppUpdateProgress(78, "Applying updated package...", "The updater command finished. Preparing UI restart.");
    pushAppUpdateOutput("[3/4] Upgrade command finished.");
    const output = [String(data?.stdout || "").trim(), String(data?.stderr || "").trim()].filter(Boolean).join("\\n\\n");
    summarizeUpdateOutput(output).forEach((line) => pushAppUpdateOutput(`  ${line}`));
    if(!data?.updated){
      throw new Error(String(data?.stderr || data?.error || "Update failed."));
    }
    setAppUpdateProgress(92, "Restarting web panel...", "Reloading the UI service so the new version is active.");
    pushAppUpdateOutput("[4/4] Restarting UI service...");
    showInAppNotice("Update Complete", "App updated successfully. Restarting the UI service now.", { duration_ms: 9000 });
    closeUpdateModal();
    await restartUiService();
    setAppUpdateProgress(100, "Update complete", "The app finished upgrading successfully.");
  } catch(e){
    if(e && e.name === "AbortError"){
      pushAppUpdateOutput("Update request was cancelled in this dialog.");
      setAppUpdateProgress(appUpdateProgressValue || 20, "Update request cancelled", "If the updater had already started, it may continue in the background.");
      return;
    }
    const msg = e?.message || String(e);
    setError(msg);
    pushAppUpdateOutput(`Update failed: ${msg}`);
    setAppUpdateProgress(appUpdateProgressValue || 20, "Update failed", "The updater returned an error. Review the details below.");
    pushOverlayLog("error", "app_update.failed", { error: msg });
  } finally {
    appUpdateInFlight = false;
    appUpdateRequestController = null;
    if(appUpdateProgressTimer){
      clearInterval(appUpdateProgressTimer);
      appUpdateProgressTimer = null;
    }
    applyAppUpdateStatus(appUpdateState || {});
    renderUpdateReleaseModal(appUpdateState || {});
  }
}
async function copyText(text){
  const value = String(text || "");
  if(!value) return false;
  try {
    if(navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch(_) {}
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    ta.style.pointerEvents = "none";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return !!ok;
  } catch(_) {
    return false;
  }
}
function pushOverlayLog(level, message, details){
  const nowIso = new Date().toISOString();
  const nowMs = Date.now();
  const normalizedLevel = String(level || "info").toLowerCase();
  const normalizedMessage = String(message || "");
  const normalizedDetails = sanitizeLogDetails(details || null);
  const sig = `${normalizedLevel}|${normalizedMessage}|${safeJsonStringify(normalizedDetails)}`;
  const last = overlayLogs.length ? overlayLogs[overlayLogs.length - 1] : null;
  if(last && last._sig === sig){
    const lastMs = Number(last._last_ts_ms || 0);
    if(nowMs - lastMs <= LOG_COALESCE_WINDOW_MS){
      last.repeat_count = Number(last.repeat_count || 1) + 1;
      last._last_ts_ms = nowMs;
      last.last_ts = nowIso;
      renderSystemOut();
      return;
    }
  }
  overlayLogs.push({
    ts: nowIso,
    last_ts: nowIso,
    _last_ts_ms: nowMs,
    _sig: sig,
    repeat_count: 1,
    level: normalizedLevel,
    message: normalizedMessage,
    details: normalizedDetails,
  });
  if(overlayLogs.length > MAX_OVERLAY_LOGS) overlayLogs = overlayLogs.slice(-MAX_OVERLAY_LOGS);
  renderSystemOut();
}
function lineLevelClass(level){
  const lv = String(level || "").toLowerCase();
  if(lv.includes("error")) return "log-error";
  if(lv.includes("ui")) return "log-info";
  if(lv.includes("warn")) return "log-warn";
  if(lv.includes("event")) return "log-event";
  if(lv.includes("command")) return "log-command";
  return "log-info";
}
function renderSystemOut(){
  const box = byId("debugOut", false);
  if(!box) return;
  const merged = [...baseLogs, ...overlayLogs];
  if(!merged.length){ box.innerHTML = "<span class='log-line log-info'>No logs yet.</span>"; return; }
  const html = merged.map((r) => {
    const ts = escHtml(r.ts || "-");
    const levelRaw = String(r.level || "info").toUpperCase();
    const level = escHtml(levelRaw);
    const repeat = Number(r.repeat_count || 1);
    const msg = escHtml(r.message || "");
    const cls = lineLevelClass(r.level);
    let detailHtml = "";
    if(r.details && Object.keys(r.details || {}).length){
      detailHtml = `<span class="log-detail">${escHtml(compactDetailString(r.details))}</span>`;
    }
    const repeatBadge = repeat > 1 ? ` <span class="log-level">×${repeat}</span>` : "";
    return `<span class="log-line ${cls}"><span class="log-ts">[${ts}]</span> <span class="log-level">${level}</span>${msg}${repeatBadge}</span>${detailHtml}`;
  }).join("");
  box.innerHTML = html;
  box.scrollTop = box.scrollHeight;
}
function setCmdOut(title,data){
  if(!data) return;
  const msg = `action=${title} exit=${data.exit_code ?? "-"}`;
  pushOverlayLog("command", msg, {
    stdout: (data.stdout || "").trim(),
    stderr: (data.stderr || "").trim(),
  });
}
async function runAction(title,fn,refreshOpts=null){
  setError("");
  const startedAt = Date.now();
  pushOverlayLog("ui", `action.start ${title}`);
  try{
    const d = await fn();
    setCmdOut(title,d);
    pushOverlayLog("ui", `action.success ${title}`, { duration_ms: Date.now() - startedAt });
    if(!(refreshOpts && refreshOpts.skipRefresh)){
      await refreshAll(refreshOpts || undefined);
    }
    return true;
  } catch(e){
    const msg = e?.message || String(e);
    pushOverlayLog("error", `action.fail ${title}`, { error: msg, duration_ms: Date.now() - startedAt });
    setError(msg);
    return false;
  }
}
async function runNativeNotificationTest(){
  await runAction("notifications.native_test", async ()=>{
    const payload = await postApi("/api/notifications/native-test", {});
    const profileName = String(payload?.profile_name || "").trim();
    setError(profileName ? `Native notification sent for ${profileName}.` : "Native notification sent.");
    return payload;
  }, { skipRefresh:true });
}
function exportDebugSnapshot(){
  pushOverlayLog("ui", "ui.click export_snapshot");
  const payload={
    exported_at:new Date().toISOString(),
    version:UI_VERSION,
    status:latestData.status,
    usage:latestData.usage,
    profiles:latestData.list,
    config:latestData.config,
    auto_state:latestData.autoState,
    events:latestData.events.slice(-200),
    logs:getMergedLogs(2000),
    client:{
      user_agent:navigator.userAgent,
      language:navigator.language,
      platform:navigator.platform,
      timezone:(Intl.DateTimeFormat().resolvedOptions().timeZone || null),
      viewport:{ width: window.innerWidth, height: window.innerHeight },
    },
  };
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download="codex-account-snapshot-"+Date.now()+".json";
  document.body.appendChild(a);
  a.click();
  setTimeout(()=>{URL.revokeObjectURL(a.href); a.remove();},200);
}

function rowKey(row,key){
  switch(key){
    case "current": return row.is_current ? 1 : 0;
    case "name": return (row.name||"").toLowerCase();
    case "email": return (row.email||"").toLowerCase();
    case "planType": return (row.plan_type||"").toLowerCase();
    case "isPaid": {
      if(row.is_paid === true) return 2;
      if(row.is_paid === false) return 1;
      return 0;
    }
    case "id": return (row.account_id||"").toLowerCase();
    case "usage5": return Number(row.usage_5h?.remaining_percent ?? -1);
    case "usage5remain": {
      const ts = Number(row.usage_5h?.resets_at ?? 0);
      return ts ? Math.max(0, ts - (Date.now()/1000)) : 0;
    }
    case "usageW": return Number(row.usage_weekly?.remaining_percent ?? -1);
    case "usageWremain": {
      const ts = Number(row.usage_weekly?.resets_at ?? 0);
      return ts ? Math.max(0, ts - (Date.now()/1000)) : 0;
    }
    case "usage5reset": return Number(row.usage_5h?.resets_at ?? 0);
    case "usageWreset": return Number(row.usage_weekly?.resets_at ?? 0);
    case "savedAt": return row.saved_at_ts || 0;
    case "note": return row.same_principal ? 1 : 0;
    default: return 0;
  }
}

function fmtPaid(v){
  if(v === true) return "yes";
  if(v === false) return "no";
  return "-";
}

function applySort(rows){
  const key=sortState.key||"savedAt"; const dir=sortState.dir==="asc"?1:-1;
  const withIdx=rows.map((r,i)=>({r,i})); const current=withIdx.filter(x=>x.r.is_current); const others=withIdx.filter(x=>!x.r.is_current);
  others.sort((aObj,bObj)=>{ const a=aObj.r,b=bObj.r; const av=rowKey(a,key), bv=rowKey(b,key);
    if(typeof av==="string" || typeof bv==="string"){ const cmp=String(av).localeCompare(String(bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i; }
    const cmp=((av>bv)-(av<bv))*dir; if(cmp!==0) return cmp; return aObj.i-bObj.i;
  });
  return [...current.map(x=>x.r), ...others.map(x=>x.r)];
}
function waitMs(ms){
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}
function getRowRectByName(name){
  const target = String(name || "").trim();
  if(!target) return null;
  try{
    const row = byId("rows", false)?.querySelector(`tr[data-row-name="${CSS.escape(target)}"]`);
    if(!row) return null;
    const rect = row.getBoundingClientRect();
    if(!Number.isFinite(rect.left) || !Number.isFinite(rect.top)) return null;
    return { left: rect.left, top: rect.top };
  } catch(_) {
    return null;
  }
}
function applyOptimisticSwitchTarget(targetName){
  const target = String(targetName || "").trim();
  const usage = latestData?.usage;
  if(!target || !usage || !Array.isArray(usage.profiles) || !usage.profiles.length) return false;
  let found = false;
  const nextProfiles = usage.profiles.map((profile) => {
    const rowName = String(profile?.name || "").trim();
    const isTarget = rowName === target;
    if(isTarget) found = true;
    return {
      ...profile,
      is_current: isTarget,
    };
  });
  if(!found) return false;
  latestData.usage = {
    ...usage,
    current_profile: target,
    profiles: nextProfiles,
  };
  renderTable(latestData.usage);
  return true;
}
async function animateSwitchFromEvent(ev){
  const targetFromEvent = String(ev?.details?.target || "").trim();
  const fromRect = getRowRectByName(targetFromEvent);
  const optimisticApplied = applyOptimisticSwitchTarget(targetFromEvent);
  if(optimisticApplied && targetFromEvent){
    await animateSwitchRowToTop(targetFromEvent, fromRect);
  }
  const prevSuppress = suppressCurrentProfileAutoAnimation;
  suppressCurrentProfileAutoAnimation = true;
  try{
    await refreshAll({ showLoading:false, clearUsageCache:true, usageForce:true });
  } finally {
    suppressCurrentProfileAutoAnimation = prevSuppress;
  }
  const target = targetFromEvent || String(latestData?.usage?.current_profile || "").trim();
  if(target && !optimisticApplied){
    await animateSwitchRowToTop(target, fromRect);
  }
}
async function animateSwitchFromEventLocal(ev){
  const targetFromEvent = String(ev?.details?.target || "").trim();
  const fromRect = getRowRectByName(targetFromEvent);
  const optimisticApplied = applyOptimisticSwitchTarget(targetFromEvent);
  const target = targetFromEvent || String(latestData?.usage?.current_profile || "").trim();
  if(target && optimisticApplied){
    await animateSwitchRowToTop(target, fromRect);
  }
}
async function animateSwitchRowToTop(name, fromRect=null){
  const tbody = byId("rows", false);
  if(!tbody) return;
  const source = tbody.querySelector(`tr[data-row-name="${CSS.escape(String(name || ""))}"]`);
  if(!source) return;
  if(fromRect && Number.isFinite(fromRect.top) && Number.isFinite(fromRect.left)){
    const dstRect = source.getBoundingClientRect();
    const dx = fromRect.left - dstRect.left;
    const dy = fromRect.top - dstRect.top;
    if(Math.abs(dx) > 2 || Math.abs(dy) > 2){
      source.style.position = "relative";
      source.style.zIndex = "3";
      source.style.transition = "none";
      source.style.transform = `translate(${dx}px, ${dy}px)`;
      source.style.boxShadow = "0 14px 34px color-mix(in srgb,var(--accent-glow) 34%, transparent)";
      void source.offsetWidth;
      source.classList.add("switch-row-activated");
      source.style.transition = "transform .72s cubic-bezier(0.2, 0.9, 0.2, 1), box-shadow .72s ease";
      source.style.transform = "translate(0, 0)";
      source.style.boxShadow = "0 10px 22px color-mix(in srgb,var(--accent-glow) 18%, transparent)";
      await waitMs(760);
      source.classList.remove("switch-row-activated");
      source.style.transition = "";
      source.style.transform = "";
      source.style.boxShadow = "";
      source.style.position = "";
      source.style.zIndex = "";
      return;
    }
  }
  source.classList.add("switch-row-activated");
  await waitMs(240);
  source.classList.remove("switch-row-activated");
}
function renderSortIndicators(){
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    const key = th.dataset.sort;
    const active = sortState.key === key;
    th.classList.toggle("sorted", active);
    let indicator = th.querySelector(".sort-indicator");
    if(!indicator){
      indicator = document.createElement("span");
      indicator.className = "sort-indicator";
      th.appendChild(indicator);
    }
    indicator.textContent = active ? (sortState.dir === "asc" ? "↑" : "↓") : "";
  });
}

function initSteppers(root){
  const scope = root || document;
  scope.querySelectorAll("[data-stepper]").forEach((wrap) => {
    if (wrap.dataset.bound === "1") return;
    const input = wrap.querySelector("input[type='number']");
    const dec = wrap.querySelector("[data-stepper-dec]");
    const inc = wrap.querySelector("[data-stepper-inc]");
    if (!input || !dec || !inc) return;
    const applyDelta = (sign) => {
      const step = Number(input.step || "1") || 1;
      const min = input.min !== "" ? Number(input.min) : null;
      const max = input.max !== "" ? Number(input.max) : null;
      let next = Number(input.value || "0");
      if (!Number.isFinite(next)) next = 0;
      next = next + (sign * step);
      if (min !== null && Number.isFinite(min)) next = Math.max(min, next);
      if (max !== null && Number.isFinite(max)) next = Math.min(max, next);
      if (Math.abs(step - Math.round(step)) < 1e-9) next = Math.round(next);
      input.value = String(next);
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    let holdTimer = null;
    let holdInterval = null;
    let holdTriggered = false;
    let pointerUsed = false;
    const clearHold = () => {
      if(holdTimer){ clearTimeout(holdTimer); holdTimer = null; }
      if(holdInterval){ clearInterval(holdInterval); holdInterval = null; }
    };
    const startHold = (sign) => {
      clearHold();
      holdTriggered = false;
      applyDelta(sign);
      holdTimer = setTimeout(() => {
        holdTriggered = true;
        holdInterval = setInterval(() => applyDelta(sign), 70);
      }, 320);
    };
    const bindStepperButton = (btn, sign) => {
      btn.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        pointerUsed = true;
        btn.setPointerCapture?.(ev.pointerId);
        startHold(sign);
      });
      btn.addEventListener("pointerup", clearHold);
      btn.addEventListener("pointercancel", clearHold);
      btn.addEventListener("pointerleave", clearHold);
      // keyboard fallback
      btn.addEventListener("click", () => {
        if(pointerUsed){ pointerUsed = false; return; }
        if(holdTriggered){ holdTriggered = false; return; }
        applyDelta(sign);
      });
    };
    bindStepperButton(dec, -1);
    bindStepperButton(inc, +1);
    wrap.dataset.bound = "1";
  });
}
function saveColumnPrefs(){
  try {
    columnPrefs = normalizeColumnPrefs(columnPrefs);
    localStorage.setItem("codex_table_columns", JSON.stringify(columnPrefs));
  } catch(_) {}
}
function isAutoSwitchEnabled(){
  try { return !!(latestData.config && latestData.config.auto_switch && latestData.config.auto_switch.enabled); } catch(_) { return false; }
}
function applyColumnVisibility(){
  Object.keys(defaultColumns).forEach((k) => {
    let visible = requiredColumns.has(k) ? true : !!columnPrefs[k];
    if(k === "auto" && !isAutoSwitchEnabled()) visible = false;
    document.querySelectorAll(`[data-col="${k}"]`).forEach((el) => {
      if (visible) el.classList.remove("col-hidden");
      else el.classList.add("col-hidden");
    });
  });
}
function renderColumnsModal(){
  const panel = byId("columnsModalList", false);
  if(!panel) return;
  panel.innerHTML = "";
  Object.keys(defaultColumns).forEach((k) => {
    if(k === "auto" && !isAutoSwitchEnabled()) return;
    if(requiredColumns.has(k)) return;
    const wrap = document.createElement("div");
    wrap.className = "columns-item";
    const row = document.createElement("label");
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = !!columnPrefs[k];
    chk.addEventListener("change", () => {
      columnPrefs[k] = !!chk.checked;
      saveColumnPrefs();
      applyColumnVisibility();
    });
    const txt = document.createElement("span");
    txt.textContent = columnLabels[k] || k;
    row.appendChild(chk);
    row.appendChild(txt);
    wrap.appendChild(row);
    panel.appendChild(wrap);
  });
}
function openColumnsModal(){
  renderColumnsModal();
  const b = byId("columnsModalBackdrop", false);
  if(b) b.style.display = "flex";
}
function closeColumnsModal(){
  const b = byId("columnsModalBackdrop", false);
  if(b) b.style.display = "none";
}
function getExportableProfiles(){
  const rows = Array.isArray(latestData?.list?.profiles) ? latestData.list.profiles : [];
  return rows.map((row) => ({ name: String(row?.name || "").trim(), account_hint: String(row?.account_hint || row?.email || "-") })).filter((row) => !!row.name);
}
function setImportFileLabel(text=""){
  const label = byId("importFileLabel", false);
  if(!label) return;
  label.textContent = String(text || "").trim();
}
function syncExportSelection(rows, selectedNames){
  const selectedSet = new Set((selectedNames || []).map((name) => String(name || "").trim()).filter(Boolean));
  return rows.filter((row) => selectedSet.has(row.name)).map((row) => row.name);
}
function updateExportSelectedSummary(){
  const rows = getExportableProfiles();
  exportSelectedNames = syncExportSelection(rows, exportSelectedNames);
  updateExportProfilesSummary(rows);
}
function updateExportProfilesSummary(rows){
  const summary = byId("exportProfilesSummary", false);
  const confirmBtn = byId("exportProfilesConfirmBtn", false);
  const headerCheckbox = byId("exportHeaderCheckbox", false);
  if(!summary) return;
  const selectedCount = exportSelectedNames.length;
  if(confirmBtn) confirmBtn.disabled = !rows.length || selectedCount === 0;
  if(headerCheckbox){
    headerCheckbox.checked = !!rows.length && selectedCount === rows.length;
    headerCheckbox.indeterminate = selectedCount > 0 && selectedCount < rows.length;
    headerCheckbox.disabled = rows.length === 0;
  }
  if(!rows.length){
    summary.textContent = "No saved profiles are available.";
    return;
  }
  summary.textContent = `${selectedCount} of ${rows.length} profile(s) selected for export.`;
}
function toggleAllExportProfiles(checked){
  const rows = getExportableProfiles();
  exportSelectedNames = checked ? rows.map((row) => row.name) : [];
  renderExportProfilesModal();
}
function renderExportProfilesModal(){
  const panel = byId("exportProfilesTableBody", false);
  if(!panel) return;
  panel.innerHTML = "";
  const rows = getExportableProfiles();
  exportSelectedNames = syncExportSelection(rows, exportSelectedNames);
  if(!rows.length){
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.className = "export-modal-hint";
    td.textContent = "No saved profiles are available.";
    tr.appendChild(td);
    panel.appendChild(tr);
    updateExportProfilesSummary(rows);
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const checkboxCell = document.createElement("td");
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = exportSelectedNames.includes(row.name);
    chk.addEventListener("change", () => {
      if(chk.checked){
        if(!exportSelectedNames.includes(row.name)) exportSelectedNames.push(row.name);
      } else {
        exportSelectedNames = exportSelectedNames.filter((name) => name !== row.name);
      }
      updateExportProfilesSummary(rows);
    });
    checkboxCell.appendChild(chk);
    const nameCell = document.createElement("td");
    const nameText = document.createElement("div");
    nameText.className = "export-modal-name";
    nameText.textContent = row.name;
    nameCell.appendChild(nameText);
    const hintCell = document.createElement("td");
    hintCell.className = "export-modal-hint";
    hintCell.textContent = row.account_hint || "-";
    tr.appendChild(checkboxCell);
    tr.appendChild(nameCell);
    tr.appendChild(hintCell);
    panel.appendChild(tr);
  });
  updateExportProfilesSummary(rows);
}
function openExportProfilesModal(){
  const rows = getExportableProfiles();
  exportSelectedNames = rows.map((row) => row.name);
  const filenameInput = byId("exportFilenameInput", false);
  if(filenameInput) filenameInput.value = "";
  renderExportProfilesModal();
  const b = byId("exportProfilesBackdrop", false);
  if(b) b.style.display = "flex";
}
function closeExportProfilesModal(){
  const b = byId("exportProfilesBackdrop", false);
  if(b) b.style.display = "none";
}
async function fileToBase64(file){
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for(let i=0;i<bytes.length;i+=chunk){
    const slice = bytes.subarray(i, i + chunk);
    binary += String.fromCharCode.apply(null, slice);
  }
  return btoa(binary);
}
function closeImportReviewModal(){
  importReviewState = null;
  const b = byId("importReviewBackdrop", false);
  if(b) b.style.display = "none";
}
function renderImportReviewModal(){
  const list = byId("importReviewList", false);
  const summary = byId("importReviewSummary", false);
  if(!list || !summary || !importReviewState) return;
  list.innerHTML = "";
  const rows = Array.isArray(importReviewState.profiles) ? importReviewState.profiles : [];
  rows.forEach((row) => {
    const card = document.createElement("div");
    card.className = "review-item";
    const head = document.createElement("div");
    head.className = "review-item-head";
    const left = document.createElement("div");
    const name = document.createElement("div");
    name.className = "review-name";
    name.textContent = row.name || "-";
    const hint = document.createElement("div");
    hint.className = "review-hint";
    hint.textContent = row.account_hint || "-";
    left.appendChild(name);
    left.appendChild(hint);
    const badge = document.createElement("div");
    const statusClass = row.status === "ready" ? "ready" : ((row.status || "").includes("conflict") ? "conflict" : "invalid");
    badge.className = `review-status ${statusClass}`;
    badge.textContent = String(row.status || "unknown").replaceAll("_", " ");
    head.appendChild(left);
    head.appendChild(badge);
    card.appendChild(head);
    if(Array.isArray(row.problems) && row.problems.length){
      const ul = document.createElement("ul");
      ul.className = "review-problems";
      row.problems.forEach((msg) => {
        const li = document.createElement("li");
        li.textContent = msg;
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }
    const actions = document.createElement("div");
    actions.className = "review-actions";
    const select = document.createElement("select");
    [
      { value:"import", label:"Import" },
      { value:"skip", label:"Skip" },
      { value:"rename", label:"Rename" },
      { value:"overwrite", label:"Overwrite" },
    ].forEach((opt) => {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      if(opt.value === "overwrite" && !row.existing_name) el.disabled = true;
      select.appendChild(el);
    });
    select.value = row.action || (row.status === "ready" ? "import" : "skip");
    const rename = document.createElement("input");
    rename.type = "text";
    rename.placeholder = "new profile name";
    rename.value = row.rename_to || "";
    rename.style.display = select.value === "rename" ? "" : "none";
    select.addEventListener("change", () => {
      row.action = select.value;
      rename.style.display = select.value === "rename" ? "" : "none";
    });
    rename.addEventListener("input", () => {
      row.rename_to = rename.value;
    });
    actions.appendChild(select);
    actions.appendChild(rename);
    card.appendChild(actions);
    list.appendChild(card);
  });
  const total = rows.length;
  const importCount = rows.filter((row) => (row.action || "skip") !== "skip").length;
  const overwriteCount = rows.filter((row) => row.action === "overwrite").length;
  summary.textContent = `Profiles in archive: ${total}. Selected for apply: ${importCount}. Overwrite actions: ${overwriteCount}.`;
}
function openImportReviewModal(payload){
  importReviewState = JSON.parse(JSON.stringify(payload || {}));
  byId("importReviewIntro").textContent = `Archive: ${importReviewState.filename || "uploaded file"}. Review each profile before applying this import.`;
  renderImportReviewModal();
  const b = byId("importReviewBackdrop", false);
  if(b) b.style.display = "flex";
}
async function startProfilesExportFlow(){
  const rows = getExportableProfiles();
  const names = syncExportSelection(rows, exportSelectedNames);
  if(!names.length){
    setError("Select at least one profile to export.");
    return;
  }
  const requestedFilename = String(byId("exportFilenameInput", false)?.value || "").trim();
  const payload = await postApi("/api/local/export/prepare", {
    scope: "selected",
    names,
    filename: requestedFilename,
  });
  const href = `/api/local/export/download?token=${encodeURIComponent(token)}&id=${encodeURIComponent(payload.export_id)}`;
  const res = await fetch(href, { method: "GET", cache: "no-store", credentials: "same-origin" });
  if(!res.ok){
    let detail = `download failed (${res.status})`;
    try{
      const errPayload = await res.json();
      detail = errPayload?.error?.message || detail;
    } catch(_) {}
    throw new Error(detail);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = payload.filename || "profiles.camzip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => {
    try { URL.revokeObjectURL(objectUrl); } catch(_) {}
  }, 1500);
  closeExportProfilesModal();
  showInAppNotice("Export Ready", `Downloaded ${payload.count || 0} profile(s) as a migration archive.`, { duration_ms: 7000 });
}
async function startProfilesImportFlow(file){
  if(!file) return;
  setImportFileLabel(`Selected file: ${file.name}`);
  const warning = await openModal({
    title: "Import Profiles",
    body: "Imported data may grant account access and should only come from a trusted source. Keep exported files private, do not share them with other people, and use this feature at your own risk.\\n\\nContinue and analyze this archive?",
    okText: "Analyze Import",
    okClass: "btn-warning",
  });
  if(!warning || !warning.ok){
    byId("importProfilesInput").value = "";
    return;
  }
  const content_b64 = await fileToBase64(file);
  const payload = await postApi("/api/local/import/analyze", {
    filename: file.name,
    content_b64,
  });
  openImportReviewModal(payload);
}
function openRowActionsModal(name){
  activeRowActionsName = name || null;
  const target = byId("rowActionsTarget", false);
  if(target) target.textContent = name ? `Profile: ${name}` : "-";
  const b = byId("rowActionsBackdrop", false);
  if(b) b.style.display = "flex";
}
function closeRowActionsModal(){
  activeRowActionsName = null;
  const b = byId("rowActionsBackdrop", false);
  if(b) b.style.display = "none";
}
async function renameProfileFlow(oldName){
  const inputRes = await openModal({ title:"Rename Profile", body:"Enter the new profile name:", input:true, inputValue:oldName, inputPlaceholder:"new name" });
  if(!inputRes || !inputRes.ok) return;
  const newName = (inputRes.value || "").trim();
  if(!newName || newName===oldName) return;
  const confirmRes = await openModal({ title:"Confirm Rename", body:"From: "+oldName+"\\nTo: "+newName });
  if(!confirmRes || !confirmRes.ok) return;
  await runAction("local.rename", ()=>postApi("/api/local/rename",{old_name:oldName,new_name:newName}));
}
async function removeProfileFlow(name){
  const ok = await openModal({ title:"Confirm Remove", body:"Remove profile '"+name+"'?" });
  if(!ok || !ok.ok) return;
  await runAction("local.remove", ()=>postApi("/api/local/remove",{name}));
}
function clearAddDevicePolling(){
  if(addDevicePollTimer){
    clearInterval(addDevicePollTimer);
    addDevicePollTimer = null;
  }
}
function openAddDeviceModal(opts={}){
  if(opts.reset){
    clearAddDevicePolling();
    addDeviceSessionId = null;
    addDeviceSessionState = null;
    addDeviceProfileName = String(opts.name || "").trim();
    const nameInput = byId("addDeviceNameInput", false);
    if(nameInput){
      nameInput.value = addDeviceProfileName;
      setTimeout(()=>nameInput.focus(), 0);
    }
    updateAddDeviceModal({ status:"idle", message:"Choose a login method to begin.", url:null, code:null });
  }
  const b = byId("addDeviceBackdrop", false);
  if(b) b.style.display = "flex";
}
function closeAddDeviceModal(){
  clearAddDevicePolling();
  addDeviceSessionId = null;
  addDeviceSessionState = null;
  addDeviceProfileName = "";
  const nameInput = byId("addDeviceNameInput", false);
  if(nameInput) nameInput.value = "";
  const b = byId("addDeviceBackdrop", false);
  if(b) b.style.display = "none";
}
function getAddDeviceProfileName(){
  const input = byId("addDeviceNameInput", false);
  const name = String((input?.value || addDeviceProfileName || "")).trim();
  if(!name){
    setError("Enter profile name for the new login.");
    if(input) input.focus();
    return "";
  }
  const existing = Array.isArray(latestData.list?.profiles) ? latestData.list.profiles : [];
  const taken = existing.some((p) => String(p?.name || "").toLowerCase() === name.toLowerCase());
  if(taken){
    setError(`Profile name '${name}' already exists. Choose a different name.`);
    if(input) input.focus();
    return "";
  }
  return name;
}
function updateAddDeviceModal(session){
  addDeviceSessionState = session || null;
  const st = byId("addDeviceStatus", false);
  const urlEl = byId("addDeviceUrl", false);
  const codeEl = byId("addDeviceCode", false);
  const startBtn = byId("addDeviceStartBtn", false);
  const normalBtn = byId("addDeviceLegacyBtn", false);
  const copyBtn = byId("addDeviceCopyBtn", false);
  const openBtn = byId("addDeviceOpenBtn", false);
  if(st) st.textContent = session?.error || session?.message || `status: ${session?.status || "-"}`;
  if(urlEl) urlEl.textContent = session?.url || "-";
  if(codeEl) codeEl.textContent = session?.code || "-";
  const finished = !!session && ["completed", "failed", "canceled"].includes(String(session.status || ""));
  const running = !!addDeviceSessionId && !finished;
  if(startBtn) startBtn.disabled = running;
  if(normalBtn) normalBtn.disabled = running;
  if(copyBtn) copyBtn.disabled = !String(session?.url || session?.code || "").trim();
  if(openBtn) openBtn.disabled = !String(session?.url || "").trim();
}
async function pollAddDeviceSession(){
  if(!addDeviceSessionId) return;
  const payload = await safeGet(`/api/local/add/session?id=${encodeURIComponent(addDeviceSessionId)}`);
  if(payload.__error){
    updateAddDeviceModal({ status:"failed", error: payload.__error, message:`session error: ${payload.__error}` });
    clearAddDevicePolling();
    return;
  }
  updateAddDeviceModal(payload);
  if(["completed", "failed", "canceled"].includes(String(payload.status || ""))){
    clearAddDevicePolling();
    if(payload.status === "completed"){
      await refreshAll();
    }
  }
}
async function startAddDeviceFlow(name){
  clearAddDevicePolling();
  addDeviceSessionId = null;
  addDeviceProfileName = String(name || "").trim();
  const nameInput = byId("addDeviceNameInput", false);
  if(nameInput) nameInput.value = addDeviceProfileName;
  updateAddDeviceModal({ status:"running", message:"starting login flow..." });
  const data = await postApi("/api/local/add/start", { name, timeout: 600, device_auth: true });
  addDeviceSessionId = data.id;
  updateAddDeviceModal(data);
  await pollAddDeviceSession();
  addDevicePollTimer = setInterval(pollAddDeviceSession, 1200);
}
function closeModal(result){
  const b=byId("modalBackdrop", false);
  if(b) b.style.display="none";
  if(activeModalResolver){ const fn=activeModalResolver; activeModalResolver=null; fn(result); }
}
function modalOkAction(){
  const input=byId("modalInput");
  closeModal({ ok:true, value: (input && input.style.display !== "none") ? input.value : "" });
}
function modalCancelAction(){
  closeModal({ ok:false });
}
function openModal(opts){
  return new Promise((resolve) => {
    activeModalResolver = resolve;
    byId("modalTitle").textContent = opts.title || "Confirm";
    byId("modalBody").textContent = opts.body || "";
    const okBtn = byId("modalOkBtn", false);
    const cancelBtn = byId("modalCancelBtn", false);
    if(okBtn){
      okBtn.textContent = opts.okText || "OK";
      okBtn.className = `btn ${opts.okClass || "btn-primary"}`;
    }
    if(cancelBtn){
      cancelBtn.textContent = opts.cancelText || "Cancel";
      cancelBtn.className = `btn ${opts.cancelClass || ""}`.trim() || "btn";
      cancelBtn.style.display = opts.hideCancel ? "none" : "";
    }
    const input = byId("modalInput");
    if(opts.input){
      input.style.display = "block";
      input.value = opts.inputValue || "";
      input.placeholder = opts.inputPlaceholder || "";
      setTimeout(()=>input.focus(), 0);
    } else {
      input.style.display = "none";
      input.value = "";
    }
    byId("modalBackdrop").style.display = "flex";
  });
}

async function saveUiConfigPatch(patch){
  await enqueueConfigPatch(patch);
}

async function setEligibility(name, eligible){ await postApi("/api/auto-switch/account-eligibility", { name, eligible }); }
const IS_MAC_CLIENT = /mac os|macintosh/i.test((navigator && navigator.userAgent) || "");
function switchRequestBody(name){
  if(IS_MAC_CLIENT) return { name };
  return { name, close_only: true, no_restart: true };
}
async function switchProfile(name){
  await postApi("/api/switch", switchRequestBody(name));
}
function renderSwitchProgressState(){
  if(latestData.usage && Array.isArray(latestData.usage.profiles)){
    renderTable(latestData.usage);
  }
}
function renderAutoSwitchActionButtons(autoStateOverride=null){
  const autoState = (autoStateOverride && typeof autoStateOverride === "object") ? autoStateOverride : (latestData?.autoState || {});
  const runBtn = byId("asRunSwitchBtn", false);
  if(runBtn){
    const activeRun = !!autoSwitchRunActionInFlight || !!autoState.switch_in_flight;
    const disableRun = activeRun || !!autoSwitchRapidActionInFlight || !!autoState.rapid_test_active;
    runBtn.disabled = disableRun;
    runBtn.textContent = activeRun ? "Running..." : "Run Switch";
    runBtn.classList.add("btn-primary");
    runBtn.classList.toggle("btn-progress", activeRun);
  }
  const rapidBtn = byId("asRapidTestBtn", false);
  if(rapidBtn){
    const activeRapid = !!autoSwitchRapidActionInFlight || !!autoState.rapid_test_active;
    const disableRapid = activeRapid || !!autoSwitchRunActionInFlight || !!autoState.switch_in_flight;
    rapidBtn.disabled = disableRapid;
    rapidBtn.textContent = activeRapid ? "Rapid Running..." : "Rapid Test";
    rapidBtn.classList.toggle("btn-progress", activeRapid);
  }
}
async function refreshAutoSwitchState(){
  const payload = await safeGet("/api/auto-switch/state", { timeoutMs: 2500 });
  if(payload.__error) return;
  latestData.autoState = payload;
  renderAutoSwitchActionButtons(payload);
  updateAutoSwitchArmedUI();
}
async function runSwitchAction(name){
  const target = String(name || "").trim();
  if(!target) return;
  if(switchInFlight){
    return;
  }
  let startRect = null;
  try{
    const row = byId("rows", false)?.querySelector(`tr[data-row-name="${CSS.escape(target)}"]`);
    if(row){
      const rect = row.getBoundingClientRect();
      startRect = { left: rect.left, top: rect.top };
    }
  } catch(_) {}
  switchInFlight = true;
  switchPendingName = target;
  renderSwitchProgressState();
  try{
    await switchProfile(target);
    suppressCurrentProfileAutoAnimation = true;
    await refreshAll({ usageTimeoutSec: 8, usageForce: true, showLoading: false });
    switchInFlight = false;
    renderSwitchProgressState();
    await waitMs(70);
    await animateSwitchRowToTop(target, startRect);
  } finally {
    suppressCurrentProfileAutoAnimation = false;
    switchInFlight = false;
    switchPendingName = "";
    renderSwitchProgressState();
  }
}
function renderEvents(items){ return items; }

async function loadDebugLogs(){
  const payload = await safeGet("/api/debug/logs?tail=240&token="+encodeURIComponent(token));
  if(payload.__error) return;
  baseLogs = (payload.logs || []).map((r) => ({
    ts: r.ts || "-",
    level: String(r.level || "info").toLowerCase(),
    message: r.message || "",
    details: (r.details && Object.keys(r.details).length) ? r.details : null,
  }));
  renderSystemOut();
}

async function ensureNotificationPermission(showError){
  if(!("Notification" in window)){
    if(showError) setError("Notifications are not supported in this browser.");
    return false;
  }
  if(Notification.permission === "default"){
    try { await Notification.requestPermission(); } catch(_) {}
  }
  if(Notification.permission !== "granted"){
    if(showError) setError("Notification permission is blocked. Enable it in browser settings.");
    return false;
  }
  return true;
}

async function ensureNotificationServiceWorker(){
  if(!("serviceWorker" in navigator)) return null;
  if(notificationSwRegistration) return notificationSwRegistration;
  try{
    const reg = await navigator.serviceWorker.register("/sw.js?v="+encodeURIComponent(UI_VERSION), { scope: "/" });
    notificationSwRegistration = reg || null;
    return notificationSwRegistration;
  } catch(_) {
    return null;
  }
}

async function primeAlarmAudio(){
  const AC = window.AudioContext || window.webkitAudioContext;
  if(!AC) return false;
  if(!alarmAudioCtx){
    try { alarmAudioCtx = new AC(); } catch(_) { return false; }
  }
  if(alarmAudioCtx.state === "suspended"){
    try { await alarmAudioCtx.resume(); } catch(_) {}
  }
  return alarmAudioCtx.state === "running";
}

function playNotificationAlarm(delayMs){
  if(!alarmAudioCtx || alarmAudioCtx.state !== "running") return;
  const tones = Array.isArray(DEFAULT_NOTIFICATION_TONES) ? DEFAULT_NOTIFICATION_TONES : [];
  if(!tones.length) return;
  const now = alarmAudioCtx.currentTime + Math.max(0, Number(delayMs || 0)) / 1000;
  tones.forEach((tone) => {
    try {
      const osc = alarmAudioCtx.createOscillator();
      const gain = alarmAudioCtx.createGain();
      osc.type = "triangle";
      const startAt = now + Math.max(0, Number(tone.t || 0));
      const duration = Math.max(0.06, Number(tone.d || 0.18));
      const level = Math.max(0.02, Math.min(0.22, Number(tone.g || 0.16)));
      osc.frequency.setValueAtTime(Number(tone.f || 880), startAt);
      gain.gain.setValueAtTime(0.0001, startAt);
      gain.gain.exponentialRampToValueAtTime(level, startAt + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
      osc.connect(gain);
      gain.connect(alarmAudioCtx.destination);
      osc.start(startAt);
      osc.stop(startAt + duration + 0.02);
    } catch(_) {}
  });
}

async function dispatchNativeNotification(message, delaySec, opts){
  const delayMs = Math.max(0, Number(delaySec || 0) * 1000);
  const playAlarm = !!(opts && opts.play_alarm);
  const inAppAlways = !!(opts && opts.in_app_always);
  const notificationText = String(message || "Notification");
  if(playAlarm) playNotificationAlarm(Math.max(0, delayMs - 2000));
  setTimeout(async () => {
    try {
      if(inAppAlways){
        showInAppNotice("Codex Account Manager", notificationText, { require_interaction: false });
      }
    } catch(e) {
      setError(e?.message || String(e));
    }
  }, delayMs);
}

async function maybeNotify(ev){
  const cfg = latestData.config || {};
  if(!((cfg.notifications||{}).enabled)) return;
  if(!ev || ev.id <= lastEventId || notifiedEventIds.has(ev.id)) return;
  if(ev.type !== "warning") return;
  notifiedEventIds.add(ev.id);
  showInAppNotice("Codex Account Manager", ev.message || "Usage warning", { require_interaction: false });
}

function renderTable(usage){
  const tbody = byId("rows"); tbody.innerHTML="";
  const mobileRows = byId("mobileRows", false); if(mobileRows) mobileRows.innerHTML = "";
  const mappedUsage = (usage?.profiles || []).map(p => ({...p, saved_at_ts: p.saved_at ? Date.parse(p.saved_at) || 0 : 0 }));
  const mappedFallback = (latestData?.list?.profiles || []).map(p => ({
    name: p?.name || "",
    email: "",
    account_id: p?.account_id || "",
    usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
    usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
    plan_type: null,
    is_paid: null,
    is_current: false,
    same_principal: !!p?.same_principal,
    error: null,
    saved_at: p?.saved_at || null,
    auto_switch_eligible: !!p?.auto_switch_eligible,
    loading_usage: true,
    saved_at_ts: p?.saved_at ? Date.parse(p.saved_at) || 0 : 0,
  }));
  const rows = applySort(mappedUsage.length ? mappedUsage : mappedFallback);
  const appendMinimalRows = () => {
    const base = (latestData?.list?.profiles || []).map((p) => ({
      name: p?.name || "-",
      account_id: p?.account_id || "-",
      saved_at: p?.saved_at || null,
    }));
    for(const p of base){
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td data-col="cur"><span class="status-dot" title="Account status indicator."></span></td>
        <td data-col="profile" title="${escHtml(p.name)}">${escHtml(p.name)}</td>
        <td data-col="email" class="email-cell">loading...</td>
        <td data-col="h5">${renderUsageMeter(null, true, false)}</td>
        <td data-col="h5remain" class="reset-cell loading-text">loading...</td>
        <td data-col="h5reset" class="reset-cell">-</td>
        <td data-col="weekly">${renderUsageMeter(null, true, false)}</td>
        <td data-col="weeklyremain" class="reset-cell loading-text">loading...</td>
        <td data-col="weeklyreset" class="reset-cell">-</td>
        <td data-col="plan">-</td>
        <td data-col="paid">-</td>
        <td data-col="id" class="id-cell" title="${escHtml(p.account_id)}">${escHtml(p.account_id)}</td>
        <td data-col="added" class="added-cell" title="When this profile was added to the app.">${fmtSavedAt(p.saved_at || "-")}</td>
        <td data-col="note" class="note-cell"></td>
        <td data-col="auto"><input type="checkbox" disabled title="Auto-switch eligibility loads after account usage is available." /></td>
        <td data-col="actions"><div class="actions-cell"><button class="btn btn-disabled" disabled title="Switch becomes available after the account finishes loading.">Switch</button><button class="btn actions-menu-btn btn-disabled" disabled title="Row actions become available after the account finishes loading.">⋯</button></div></td>
      `;
      tbody.appendChild(tr);
    }
  };
  for(const p of rows){
    try{
      const tr=document.createElement("tr");
      tr.dataset.rowName = p.name || "";
      const statusClass = p.is_current ? "active" : "";
      const h5Loading = isUsageLoadingState(p.usage_5h, p.error, p.loading_usage);
      const wLoading = isUsageLoadingState(p.usage_weekly, p.error, p.loading_usage);
      const h5Flash = shouldBlinkUsage(p.name, "h5", h5Loading);
      const wFlash = shouldBlinkUsage(p.name, "weekly", wLoading);
      const rowErrorLabel = usageErrorLabel(p.error);
      const h5CellHtml = (!h5Loading && rowErrorLabel) ? renderUsageErrorCell(p.error) : renderUsageMeter(p.usage_5h, h5Loading, h5Flash);
      const wCellHtml = (!wLoading && rowErrorLabel) ? renderUsageErrorCell(p.error) : renderUsageMeter(p.usage_weekly, wLoading, wFlash);
      const h5RemainText = formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error);
      const wRemainText = formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error);
      const h5RemainTs = Number(p.usage_5h?.resets_at || 0) || "";
      const wRemainTs = Number(p.usage_weekly?.resets_at || 0) || "";
      const switchTarget = switchInFlight && switchPendingName === p.name;
      if(switchTarget) tr.classList.add("switch-row-pending");
      const h5Pct = usagePercentNumber(p.usage_5h);
      const wPct = usagePercentNumber(p.usage_weekly);
      const quotaBlocked = (Number.isFinite(h5Pct) && h5Pct <= 0) || (Number.isFinite(wPct) && wPct <= 0);
      const disableSwitch = p.is_current || switchInFlight;
      tr.innerHTML = `
      <td data-col="cur"><span class="status-dot ${statusClass}" title="${p.is_current ? "Current active account." : "Saved account, not currently active."}"></span></td>
      <td data-col="profile" title="${(p.name || "-").replace(/"/g,'&quot;')}">${p.name}</td>
      <td data-col="email" class="email-cell" title="${(p.email || "-").replace(/"/g,'&quot;')}">${p.email || "-"}</td>
      <td data-col="h5">${h5CellHtml}</td>
      <td data-col="h5remain" class="reset-cell ${(h5Loading || rowErrorLabel) ? "loading-text" : ""}" data-remain-ts="${h5RemainTs}" data-remain-seconds="1" data-remain-loading="${h5Loading ? "1" : "0"}" title="Time remaining until the 5-hour usage window resets.">${h5RemainText}</td>
      <td data-col="h5reset" class="reset-cell" title="Exact reset time for the 5-hour usage window.">${fmtReset(p.usage_5h?.resets_at)}</td>
      <td data-col="weekly">${wCellHtml}</td>
      <td data-col="weeklyremain" class="reset-cell ${(wLoading || rowErrorLabel) ? "loading-text" : ""}" data-remain-ts="${wRemainTs}" data-remain-seconds="0" data-remain-loading="${wLoading ? "1" : "0"}" title="Time remaining until the weekly usage window resets.">${wRemainText}</td>
      <td data-col="weeklyreset" class="reset-cell" title="Exact reset time for the weekly usage window.">${fmtReset(p.usage_weekly?.resets_at)}</td>
      <td data-col="plan" title="Detected account plan type.">${p.plan_type || "-"}</td>
      <td data-col="paid" title="Whether this account appears to be paid.">${fmtPaid(p.is_paid)}</td>
      <td data-col="id" class="id-cell" title="${(p.account_id || "-").replace(/"/g,'&quot;')}">${p.account_id || "-"}</td>
      <td data-col="added" class="added-cell" title="When this profile was added to the app.">${fmtSavedAt(p.saved_at || "-")}</td>
      <td data-col="note" class="note-cell" title="${p.same_principal ? "This profile shares the same principal identity as another saved profile." : "No extra note for this profile."}">${p.same_principal ? '<span class="badge">same-principal</span>' : ''}</td>
      <td data-col="auto"><input type="checkbox" data-auto="${p.name}" ${p.auto_switch_eligible ? "checked" : ""} title="Allow or block this profile from automatic switching." /></td>
      <td data-col="actions"><div class="actions-cell"><button class="${quotaBlocked ? "btn-primary-danger" : "btn-primary"} ${disableSwitch ? "btn-disabled" : ""} ${switchTarget ? "btn-progress" : ""}" data-switch="${p.name}" ${disableSwitch ? "disabled" : ""} title="${p.is_current ? "This profile is already active." : (quotaBlocked ? "Switch to this profile now. Warning: usage is exhausted in one of the tracked windows." : "Switch to this profile now.")}">Switch</button><button class="btn actions-menu-btn" data-row-actions="${p.name}" title="Open rename and remove actions for this profile.">⋯</button></div></td>
    `;
      tbody.appendChild(tr);
      if(mobileRows){
      const h5PctVal = usagePercentNumber(p.usage_5h);
      const wPctVal = usagePercentNumber(p.usage_weekly);
      const h5Class = usageClass(h5PctVal);
      const wClass = usageClass(wPctVal);
      const mrow = document.createElement("div");
      mrow.className = "mobile-row";
      mrow.setAttribute("tabindex", "0");
      mrow.setAttribute("title", "Tap/click to view full details");
      mrow.innerHTML = `
        <div class="mobile-head">
          <div class="mobile-left">
            <span class="status-dot ${statusClass}" title="${p.is_current ? "Current active account." : "Saved account, not currently active."}"></span>
            <span class="mobile-profile">${p.name || "-"}</span>
          </div>
          <div class="mobile-actions">
            <button class="${quotaBlocked ? "btn-primary-danger" : "btn-primary"} ${(p.is_current || switchInFlight) ? "btn-disabled" : ""} ${(switchInFlight && switchPendingName === p.name) ? "btn-progress" : ""}" data-mobile-switch="${p.name}" ${(p.is_current || switchInFlight) ? "disabled" : ""} title="${p.is_current ? "This profile is already active." : (quotaBlocked ? "Switch to this profile now. Warning: usage is exhausted in one of the tracked windows." : "Switch to this profile now.")}">Switch</button>
            <button class="btn actions-menu-btn" data-mobile-row-actions="${p.name}" title="Open rename and remove actions for this profile.">⋯</button>
          </div>
        </div>
        <div class="mobile-email">${p.email || "-"}</div>
        <div class="mobile-stats">
          <div class="mobile-stat"><span class="label">5H</span><span class="${rowErrorLabel ? "usage-low" : h5Class} ${h5Flash ? "updated" : ""}">${rowErrorLabel || fmtUsagePct(p.usage_5h)}</span></div>
          <div class="mobile-stat"><span class="label">Weekly</span><span class="${rowErrorLabel ? "usage-low" : wClass} ${wFlash ? "updated" : ""}">${rowErrorLabel || fmtUsagePct(p.usage_weekly)}</span></div>
          <div class="mobile-stat"><span class="label">5H Remain</span><span class="${(h5Loading || rowErrorLabel) ? "loading-text" : ""}">${formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error)}</span></div>
          <div class="mobile-stat"><span class="label">W Remain</span><span class="${(wLoading || rowErrorLabel) ? "loading-text" : ""}">${formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error)}</span></div>
        </div>
      `;
      const openDetails = async () => {
        const detailsBody = [
          `Profile: ${p.name || "-"}`,
          `Email: ${p.email || "-"}`,
          `Current: ${p.is_current ? "yes" : "no"}`,
          `5H Usage: ${rowErrorLabel || fmtUsagePct(p.usage_5h)}`,
          `5H Remain: ${formatRemainCell(p.usage_5h?.resets_at, true, h5Loading, p.error)}`,
          `5H Reset At: ${fmtReset(p.usage_5h?.resets_at)}`,
          `Weekly Usage: ${rowErrorLabel || fmtUsagePct(p.usage_weekly)}`,
          `Weekly Remain: ${formatRemainCell(p.usage_weekly?.resets_at, false, wLoading, p.error)}`,
          `Weekly Reset At: ${fmtReset(p.usage_weekly?.resets_at)}`,
          `Plan: ${p.plan_type || "-"}`,
          `Paid: ${fmtPaid(p.is_paid)}`,
          `Account ID: ${p.account_id || "-"}`,
          `Added: ${fmtSavedAt(p.saved_at || "-")}`,
          `Note: ${p.same_principal ? "same-principal" : "-"}`,
        ].join("\\n");
        await openModal({ title: `Account Details: ${p.name || "-"}`, body: detailsBody });
      };
      mrow.addEventListener("click", openDetails);
      mrow.addEventListener("keydown", (ev) => {
        if(ev.key === "Enter" || ev.key === " "){
          ev.preventDefault();
          openDetails();
        }
      });
      const mobileSwitchBtn = mrow.querySelector("button[data-mobile-switch]");
      if(mobileSwitchBtn){
        mobileSwitchBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          runSwitchAction(mobileSwitchBtn.dataset.mobileSwitch);
        });
      }
      const mobileRowActionsBtn = mrow.querySelector("button[data-mobile-row-actions]");
      if(mobileRowActionsBtn){
        mobileRowActionsBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          openRowActionsModal(mobileRowActionsBtn.dataset.mobileRowActions);
        });
      }
        mobileRows.appendChild(mrow);
      }
    } catch(e){
      pushOverlayLog("error", "render.row_failed", { name: p?.name || "", error: e?.message || String(e) });
    }
  }
  if(tbody.children.length === 0){
    appendMinimalRows();
  }
  applyColumnVisibility();
  refreshRemainCountdowns();
  tbody.querySelectorAll("button[data-switch]").forEach(btn => btn.addEventListener("click", () => runSwitchAction(btn.dataset.switch)));
  tbody.querySelectorAll("button[data-row-actions]").forEach(btn => btn.addEventListener("click", (e)=>{
    e.stopPropagation();
    openRowActionsModal(btn.dataset.rowActions);
  }));
  tbody.querySelectorAll("input[data-auto]").forEach(ch => ch.addEventListener("change", async ()=>{ try { await setEligibility(ch.dataset.auto, !!ch.checked); } catch(e){ setError(e.message); ch.checked=!ch.checked; } }));
}

function applyConfigToControls(cfg){
  latestConfigRevision = Number(cfg?._meta?.revision || latestConfigRevision || 1);
  const ui = cfg.ui || {};
  byId("themeSelect").value = ui.theme || "auto";
  applyTheme(ui.theme || "auto");
  updateHeaderThemeIcon(ui.theme || "auto");
  byId("advancedCard").style.display = "none";
  byId("currentAutoToggle").checked = !!ui.current_auto_refresh_enabled;
  byId("currentIntervalInput").value = String(ui.current_refresh_interval_sec || 5);
  byId("allAutoToggle").checked = !!ui.all_auto_refresh_enabled;
  byId("allIntervalInput").value = String(ui.all_refresh_interval_min || 5);
  byId("debugToggle").checked = !!ui.debug_mode;
  updateHeaderDebugIcon(!!ui.debug_mode);
  byId("debugRuntimeSection").style.display = ui.debug_mode ? "block" : "none";
  const n = cfg.notifications || {};
  byId("alarmToggle").checked = !!n.enabled;
  byId("alarm5h").value = String(n.thresholds?.h5_warn_pct ?? 20);
  byId("alarmWeekly").value = String(n.thresholds?.weekly_warn_pct ?? 20);
  const a = cfg.auto_switch || {};
  byId("asEnabled").checked = pendingAutoSwitchEnabled === null ? !!a.enabled : !!pendingAutoSwitchEnabled;
  setControlValueIfPristine("asDelay", String(a.delay_sec ?? 60));
  const rankingEl = byId("asRanking", false);
  if(rankingEl && rankingEl.dataset.dirty !== "1") rankingEl.value = a.ranking_mode || "balanced";
  updateRankingModeUI((rankingEl ? rankingEl.value : (a.ranking_mode || "balanced")), !!a.enabled);
  setControlValueIfPristine("as5h", String(a.thresholds?.h5_switch_pct ?? 20));
  setControlValueIfPristine("asWeekly", String(a.thresholds?.weekly_switch_pct ?? 20));
}

function extractEmailFromHint(hint){
  const s = String(hint || "");
  const left = s.split("|")[0].trim();
  return left.includes("@") ? left : "";
}
function buildUsageLoadingSnapshot(prevUsage, listPayload, currentPayload, errorMsg, loadingMode=false){
  const srcProfiles = [];
  if(prevUsage && Array.isArray(prevUsage.profiles) && prevUsage.profiles.length){
    for(const p of prevUsage.profiles){ srcProfiles.push({ ...p }); }
  } else if(listPayload && Array.isArray(listPayload.profiles)){
    for(const p of listPayload.profiles){
      srcProfiles.push({
        name: p.name,
        email: extractEmailFromHint(p.account_hint),
        account_id: p.account_id || "-",
        usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
        usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
        plan_type: null,
        is_paid: null,
        is_current: false,
        same_principal: !!p.same_principal,
        error: errorMsg || "request failed",
        saved_at: p.saved_at || null,
        auto_switch_eligible: !!p.auto_switch_eligible,
      });
    }
  }
  const currentEmail = (currentPayload && !currentPayload.__error) ? extractEmailFromHint(currentPayload.account_hint) : "";
  const mapped = srcProfiles.map((p) => {
    const keepCurrent = !!p.is_current;
    const byEmail = currentEmail ? (String(p.email || "").toLowerCase() === currentEmail.toLowerCase()) : keepCurrent;
    return {
      ...p,
      usage_5h: { remaining_percent: null, resets_at: null, text: "-" },
      usage_weekly: { remaining_percent: null, resets_at: null, text: "-" },
      plan_type: p.plan_type ?? null,
      is_paid: (typeof p.is_paid === "boolean") ? p.is_paid : null,
      is_current: !!byEmail,
      error: errorMsg || p.error || "request failed",
      loading_usage: !!loadingMode,
    };
  });
  const currentProfile = mapped.find((p) => p.is_current)?.name || null;
  return { refreshed_at: new Date().toISOString(), current_profile: currentProfile, profiles: mapped };
}

function buildImmediateLoadingSnapshot(reason){
  const snapshot = buildUsageLoadingSnapshot(
    latestData.usage,
    latestData.list,
    null,
    reason || "request pending",
    true,
  );
  if(snapshot && Array.isArray(snapshot.profiles) && snapshot.profiles.length){
    return snapshot;
  }
  return null;
}

function saveBootSnapshot(){
  try{
    const payload = {
      saved_at: new Date().toISOString(),
      config: latestData.config || null,
      usage: latestData.usage || null,
    };
    localStorage.setItem("cam_boot_snapshot_v1", JSON.stringify(payload));
  } catch(_) {}
}

function loadBootSnapshot(){
  try{
    const raw = localStorage.getItem("cam_boot_snapshot_v1");
    if(!raw) return null;
    const parsed = JSON.parse(raw);
    if(!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch(_) {
    return null;
  }
}

function commitUsagePayload(payload, opts={}){
  if(!payload || payload.__error) return false;
  const prevCurrentProfile = String(latestData?.usage?.current_profile || sessionUsageCache?.current_profile || "").trim();
  const nextCurrentProfile = String(payload?.current_profile || "").trim();
  const switchFromRect = (!suppressCurrentProfileAutoAnimation && prevCurrentProfile && nextCurrentProfile && prevCurrentProfile !== nextCurrentProfile)
    ? getRowRectByName(nextCurrentProfile)
    : null;
  const prevUsageForFlash = (!opts.showLoading && sessionUsageCache && Array.isArray(sessionUsageCache.profiles) && sessionUsageCache.profiles.length)
    ? sessionUsageCache
    : null;
  if(!opts.showLoading && prevUsageForFlash){
    markUsageFlashUpdates(prevUsageForFlash, payload);
  }
  latestData.usage = payload;
  sessionUsageCache = payload;
  renderTable(payload);
  if(!suppressCurrentProfileAutoAnimation && prevCurrentProfile && nextCurrentProfile && prevCurrentProfile !== nextCurrentProfile){
    setTimeout(() => {
      animateSwitchRowToTop(nextCurrentProfile, switchFromRect).catch(() => {});
    }, 50);
  }
  return true;
}

function setProfileLoadingState(name, loading, errorMsg=null){
  const target = String(name || "").trim();
  if(!target) return false;
  const currentUsage = latestData.usage;
  if(!currentUsage || !Array.isArray(currentUsage.profiles) || !currentUsage.profiles.length){
    return false;
  }
  let changed = false;
  const nextProfiles = currentUsage.profiles.map((profile) => {
    if(String(profile?.name || "").trim() !== target){
      return profile;
    }
    changed = true;
    return {
      ...profile,
      loading_usage: !!loading,
      error: loading ? null : (errorMsg || profile.error || null),
    };
  });
  if(!changed) return false;
  latestData.usage = {
    ...currentUsage,
    profiles: nextProfiles,
  };
  renderTable(latestData.usage);
  return true;
}

async function refreshCurrentUsage(opts={}){
  if(refreshRunning) return;
  if(currentRefreshRunning) return;
  currentRefreshRunning = true;
  try{
    const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 6));
    const payload = await safeGet(`/api/usage-local/current?timeout=${encodeURIComponent(String(timeoutSec))}`, {
      timeoutMs: Math.max(3500, (timeoutSec + 3) * 1000),
    });
    if(!payload.__error){
      commitUsagePayload(payload, { showLoading: false });
      return;
    }
    setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + "current usage: " + payload.__error);
  } finally {
    currentRefreshRunning = false;
  }
}

async function refreshProfileUsage(name, opts={}){
  const target = String(name || "").trim();
  if(!target) return;
  const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 7));
  setProfileLoadingState(target, true, null);
  const payload = await safeGet(`/api/usage-local/profile?name=${encodeURIComponent(target)}&timeout=${encodeURIComponent(String(timeoutSec))}`, {
    timeoutMs: Math.max(4000, (timeoutSec + 4) * 1000),
  });
  if(!payload.__error){
    commitUsagePayload(payload, { showLoading: false });
    return;
  }
  setProfileLoadingState(target, false, payload.__error || "request failed");
  setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + `usage(${target}): ` + payload.__error);
}

async function runAllAccountsSweep(opts={}){
  if(refreshRunning) return;
  if(allRefreshSweepRunning) return;
  allRefreshSweepRunning = true;
  try{
    const timeoutSec = Math.max(1, Number(opts?.timeoutSec || 7));
    const listProfiles = Array.isArray(latestData.list?.profiles) ? latestData.list.profiles : [];
    const cachedProfiles = Array.isArray(latestData.usage?.profiles) ? latestData.usage.profiles : [];
    const currentName = String(latestData.usage?.current_profile || cachedProfiles.find((p) => p?.is_current)?.name || "").trim();
    const orderedNames = [];
    for(const item of listProfiles){
      const name = String(item?.name || "").trim();
      if(!name || orderedNames.includes(name)) continue;
      orderedNames.push(name);
    }
    if(!orderedNames.length){
      for(const row of cachedProfiles){
        const name = String(row?.name || "").trim();
        if(!name || orderedNames.includes(name)) continue;
        orderedNames.push(name);
      }
    }
    for(const name of orderedNames){
      if(refreshRunning) break;
      if(currentName && name === currentName) continue;
      await refreshProfileUsage(name, { timeoutSec });
    }
  } finally {
    allRefreshSweepRunning = false;
  }
}

async function refreshAll(opts){
  if(refreshRunning){
    refreshQueuedOpts = opts || {};
    return;
  }
  refreshRunning = true;
  const runOpts = opts || {};
  const clearUsageCache = !!runOpts?.clearUsageCache;
  const showLoading = !!runOpts?.showLoading;
  if(clearUsageCache){
    sessionUsageCache = null;
    usageFlashUntil = {};
    latestData.usage = null;
  }
  if(pendingConfigSaves > 0){
    try { await configSaveQueue; } catch(_) {}
  }
  const usageTimeoutSec = Math.max(1, Number(runOpts?.usageTimeoutSec || 8));
  const usageForce = !!runOpts?.usageForce;
  const usagePath = `/api/usage-local?timeout=${encodeURIComponent(String(usageTimeoutSec))}${usageForce ? "&force=true" : ""}`;
  setError("");
  if(showLoading){
    const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
    if(!hasLiveUsage){
      const prefetchLoading = buildImmediateLoadingSnapshot("request pending");
      latestData.usage = prefetchLoading;
      renderTable(prefetchLoading);
    }
  }
  try{
    const phase1Started = Date.now();
    const phase1TimeoutMs = Math.max(2000, Number(runOpts?.phase1TimeoutMs || 4500));
    let [config, autoState, current, list] = await Promise.all([
      safeGet("/api/ui-config", { timeoutMs: phase1TimeoutMs }),
      safeGet("/api/auto-switch/state", { timeoutMs: phase1TimeoutMs }),
      safeGet("/api/current", { timeoutMs: phase1TimeoutMs }),
      safeGet("/api/list", { timeoutMs: phase1TimeoutMs }),
    ]);
    if(!config.__error){
      latestData.config = config;
      latestConfigRevision = Number(config?._meta?.revision || latestConfigRevision || 1);
      applyConfigToControls(config);
      renderColumnsModal();
      applyColumnVisibility();
    } else {
      setError("config: " + config.__error);
    }
    if(!autoState.__error){
      latestData.autoState = autoState;
      renderAutoSwitchActionButtons(autoState);
      updateAutoSwitchArmedUI();
    }
    if(!list.__error){
      latestData.list = list;
      updateExportSelectedSummary();
      if(showLoading){
        const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
        if(!hasLiveUsage){
          const listLoadingSnapshot = buildUsageLoadingSnapshot(
            latestData.usage,
            latestData.list,
            latestData.current || current,
            "request pending",
            true,
          );
          if(listLoadingSnapshot && Array.isArray(listLoadingSnapshot.profiles) && listLoadingSnapshot.profiles.length){
            latestData.usage = listLoadingSnapshot;
            renderTable(listLoadingSnapshot);
          }
        }
      }
    } else {
      const listRetry = await safeGet("/api/list", { timeoutMs: 12000 });
      if(!listRetry.__error){
        list = listRetry;
        latestData.list = listRetry;
        updateExportSelectedSummary();
        if(showLoading){
          const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
          if(!hasLiveUsage){
            const listRetrySnapshot = buildUsageLoadingSnapshot(
              latestData.usage,
              latestData.list,
              latestData.current || current,
              "request pending",
              true,
            );
            if(listRetrySnapshot && Array.isArray(listRetrySnapshot.profiles) && listRetrySnapshot.profiles.length){
              latestData.usage = listRetrySnapshot;
              renderTable(listRetrySnapshot);
            }
          }
        }
        pushOverlayLog("ui", "refresh.list.retry.success");
      }
    }
    if(!current.__error){
      latestData.current = current;
    } else {
      const currentRetry = await safeGet("/api/current", { timeoutMs: 8000 });
      if(!currentRetry.__error){
        current = currentRetry;
        latestData.current = currentRetry;
        pushOverlayLog("ui", "refresh.current.retry.success");
      }
    }
    pushOverlayLog("ui", "refresh.phase1", { duration_ms: Date.now() - phase1Started });

    const phase2Started = Date.now();
    usageFetchBlinkActive = true;
    if(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length){
      renderTable(latestData.usage);
    }
    if(showLoading){
      const hasLiveUsage = !!(latestData.usage && Array.isArray(latestData.usage.profiles) && latestData.usage.profiles.length);
      if(!hasLiveUsage){
        const pendingUsage = buildUsageLoadingSnapshot(
          latestData.usage,
          latestData.list,
          latestData.current || current,
          "request pending",
          true,
        );
        latestData.usage = pendingUsage;
        renderTable(pendingUsage);
      }
    }
    const phase2TimeoutMs = Math.max(4000, Number(runOpts?.phase2TimeoutMs || 12000));
    const [usage, autoChain, eventsPayload] = await Promise.all([
      safeGet(usagePath, { timeoutMs: Math.max(phase2TimeoutMs, (usageTimeoutSec + 4) * 1000) }),
      safeGet("/api/auto-switch/chain", { timeoutMs: phase2TimeoutMs }),
      safeGet("/api/events?since_id="+encodeURIComponent(String(lastEventId)), { timeoutMs: phase2TimeoutMs }),
    ]);
    usageFetchBlinkActive = false;
    if(!usage.__error){
      commitUsagePayload(usage, { showLoading });
    } else {
      const hasSessionCache = !!(sessionUsageCache && Array.isArray(sessionUsageCache.profiles) && sessionUsageCache.profiles.length);
      if(!showLoading && hasSessionCache){
        latestData.usage = sessionUsageCache;
        renderTable(sessionUsageCache);
      } else {
        const fallbackUsage = buildUsageLoadingSnapshot(latestData.usage, latestData.list, latestData.current || current, usage.__error);
        latestData.usage = fallbackUsage;
        renderTable(fallbackUsage);
      }
      setError((byId("error").textContent ? byId("error").textContent + "\\n" : "") + "usage: " + usage.__error);
    }
    const renderedRows = byId("rows", false)?.children?.length || 0;
    if(renderedRows === 0 && latestData.list && Array.isArray(latestData.list.profiles) && latestData.list.profiles.length){
      const forcedSnapshot = buildUsageLoadingSnapshot(
        latestData.usage,
        latestData.list,
        latestData.current || current,
        "request pending",
        true,
      );
      if(forcedSnapshot && Array.isArray(forcedSnapshot.profiles) && forcedSnapshot.profiles.length){
        latestData.usage = forcedSnapshot;
        renderTable(forcedSnapshot);
        pushOverlayLog("ui", "refresh.rows.forced_from_list", { count: forcedSnapshot.profiles.length });
      }
    }
    if(!autoChain.__error){
      latestData.autoChain = autoChain;
      renderChainPreview(autoChain);
    }
    if(!eventsPayload.__error){
      const incoming = eventsPayload.events || [];
      if(incoming.length){
        for(const ev of incoming){
          await maybeNotify(ev);
          lastEventId = Math.max(lastEventId, Number(ev.id || 0));
          latestData.events.push(ev);
          pushOverlayLog("event", `${ev.type || "event"}: ${ev.message || ""}`, ev.details || null);
          if(ev.type === "switch"){
            await animateSwitchFromEventLocal(ev);
          }
        }
      }
      renderEvents(latestData.events);
    }
    pushOverlayLog("ui", "refresh.phase2", { duration_ms: Date.now() - phase2Started });
    const debugEnabled = !!(latestData.config?.ui?.debug_mode);
    if(debugEnabled){
      await loadDebugLogs();
    }
    saveBootSnapshot();
    const refreshStamp = byId("lastRefresh", false);
    if(refreshStamp) refreshStamp.textContent = "Refreshed: " + new Date().toLocaleTimeString();
  } finally {
    usageFetchBlinkActive = false;
    refreshRunning = false;
    if(refreshQueuedOpts){
      const nextOpts = refreshQueuedOpts;
      refreshQueuedOpts = null;
      setTimeout(() => { refreshAll(nextOpts); }, 0);
    }
  }
}

function resetCurrentRefreshTimer(){
  if(currentRefreshTimer) clearInterval(currentRefreshTimer);
  const enabled = !!byId("currentAutoToggle").checked;
  if(!enabled) return;
  const iv = Math.max(1, parseInt(byId("currentIntervalInput").value || "5", 10));
  byId("currentIntervalInput").value = String(iv);
  currentRefreshTimer = setInterval(() => { refreshCurrentUsage({ timeoutSec: Math.max(2, Math.min(12, iv + 2)) }).catch(() => {}); }, iv * 1000);
}

function resetAllRefreshTimer(){
  if(allRefreshTimer) clearInterval(allRefreshTimer);
  const enabled = !!byId("allAutoToggle").checked;
  if(!enabled) return;
  const ivMin = Math.max(1, Math.min(60, parseInt(byId("allIntervalInput").value || "5", 10)));
  byId("allIntervalInput").value = String(ivMin);
  allRefreshTimer = setInterval(() => { runAllAccountsSweep({ timeoutSec: 7 }).catch(() => {}); }, ivMin * 60 * 1000);
}

function resetTimer(){
  resetCurrentRefreshTimer();
  resetAllRefreshTimer();
}
function resetRemainTicker(){
  if(remainTicker) clearInterval(remainTicker);
  remainTicker = setInterval(refreshRemainCountdowns, 1000);
}
function resetAutoSwitchStateTimer(){
  if(autoSwitchStateTimer) clearInterval(autoSwitchStateTimer);
  autoSwitchStateTimer = setInterval(() => {
    refreshAutoSwitchState().catch(() => {});
  }, 1000);
}

async function restartUiService(){
  const restartBtn = byId("restartBtn", false);
  const refreshBtn = byId("refreshBtn", false);
  const prevRestart = restartBtn ? (restartBtn.textContent || "Restart") : "Restart";
  if(restartBtn){
    restartBtn.disabled = true;
    restartBtn.textContent = "Restarting...";
  }
  if(refreshBtn) refreshBtn.disabled = true;
  setError("");
  let reloadAfterMs = 1200;
  let previousHealthVersion = "";
  try{
    const initialHealth = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
    if(!initialHealth.__error){
      previousHealthVersion = String(initialHealth?.version || "").trim();
    }
  } catch(_) {}
  try{
    const data = await postApi("/api/system/restart", {});
    reloadAfterMs = Math.max(400, Number(data?.reload_after_ms || 1200));
  } catch(e){
    const msg = e?.message || String(e);
    if(!/Failed to fetch|network/i.test(msg)){
      throw e;
    }
  }
  setError("Restarting UI service...");
  await waitMs(reloadAfterMs);
  const startedAt = Date.now();
  let sawServiceDrop = false;
  while((Date.now() - startedAt) < 20000){
    const health = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
    if(health.__error){
      sawServiceDrop = true;
    } else {
      const nextVersion = String(health?.version || "").trim();
      const versionChanged = !!nextVersion && !!previousHealthVersion && nextVersion !== previousHealthVersion;
      if(sawServiceDrop || versionChanged || !previousHealthVersion){
        try {
          window.location.href = "/?r="+Date.now();
          return;
        } catch(_) {}
      }
    }
    await waitMs(700);
  }
  const fallbackStartedAt = Date.now();
  while((Date.now() - fallbackStartedAt) < 4000){
    const health = await safeGet(`/api/health?r=${Date.now()}`, { timeoutMs: 900 });
    if(!health.__error){
      try {
        window.location.href = "/?r="+Date.now();
        return;
      } catch(_) {}
    }
    await waitMs(700);
  }
  if(restartBtn){
    restartBtn.disabled = false;
    restartBtn.textContent = prevRestart;
  }
  if(refreshBtn) refreshBtn.disabled = false;
  throw new Error("UI restart timed out. Reload the page manually.");
}

async function init(){
  try {
    installDiagnosticsHooks();
    document.addEventListener("pointerdown", () => { primeAlarmAudio().catch(()=>{}); }, { once: true });
    const settingsBtn = byId("settingsToggleBtn", false);
    if(settingsBtn){
      const hidden = localStorage.getItem("cam_settings_hidden") === "1";
      applySettingsSectionVisibility(hidden);
      settingsBtn.addEventListener("click", () => {
        const firstSection = document.querySelector("[data-settings-section='1']");
        const currentlyHidden = !!firstSection && firstSection.style.display === "none";
        const nextHidden = !currentlyHidden;
        applySettingsSectionVisibility(nextHidden);
        localStorage.setItem("cam_settings_hidden", nextHidden ? "1" : "0");
      });
    }
    const guideDetails = byId("guideDetails", false);
    if(guideDetails){
      guideDetails.addEventListener("toggle", () => {
        if(guideDetails.open && !guideReleaseLoaded){
          loadGuideReleaseNotes(false).catch(() => {});
        }
      });
      if(guideDetails.open && !guideReleaseLoaded){
        loadGuideReleaseNotes(false).catch(() => {});
      }
    }
    const guideReleaseRefreshBtn = byId("guideReleaseRefreshBtn", false);
    if(guideReleaseRefreshBtn){
      guideReleaseRefreshBtn.addEventListener("click", () => {
        loadGuideReleaseNotes(true).catch(() => {});
      });
    }
    byId("refreshBtn").addEventListener("click", async () => {
      const btn = byId("refreshBtn", false);
      const prev = btn ? (btn.textContent || "Refresh") : "Refresh";
      if(btn){
        btn.disabled = true;
        btn.textContent = "Refreshing...";
      }
      try{
        const waitStart = Date.now();
        while(refreshRunning && (Date.now() - waitStart) < 8000){
          await waitMs(60);
        }
        await refreshAll({ showLoading: true, clearUsageCache: true });
      } finally {
        if(btn){
          btn.disabled = false;
          btn.textContent = prev;
        }
      }
    });
    byId("restartBtn").addEventListener("click", async ()=>{
      try{
        await loadAppUpdateStatus(true);
        await restartUiService();
      } catch(e){
        setError(e?.message || String(e));
      }
    });
    byId("killAllBtn").addEventListener("click", async ()=>{
      const ask = await openModal({
        title: "Kill All",
        body: "Stop all Codex Account Manager processes and close this page?\\n\\nThis will force-stop current operations.",
        okText: "Kill All",
        okClass: "btn-primary-danger",
        cancelText: "Cancel",
      });
      if(!ask || !ask.ok) return;
      const btn = byId("killAllBtn", false);
      const prev = btn ? (btn.textContent || "Kill All") : "Kill All";
      if(btn){
        btn.disabled = true;
        btn.textContent = "Killing...";
      }
      setError("");
      try{
        await postApi("/api/system/kill-all", {});
        setTimeout(() => {
          try { window.close(); } catch(_) {}
          try { location.replace("about:blank"); } catch(_) {}
        }, 160);
      } catch(e){
        setError(e?.message || String(e));
        if(btn){
          btn.disabled = false;
          btn.textContent = prev;
        }
      }
    });
    byId("themeSelect").addEventListener("change", async (e) => { applyTheme(e.target.value); await saveUiConfigPatch({ ui: { theme: e.target.value } }); });
    const updateBtn = byId("appUpdateBtn", false);
    if(updateBtn){
      updateBtn.addEventListener("click", ()=>openUpdateModal());
    }
    const themeBtn = byId("themeIconBtn", false);
    if(themeBtn){
      themeBtn.addEventListener("click", () => {
        const select = byId("themeSelect");
        const order = ["auto", "dark", "light"];
        const current = select.value || "auto";
        const idx = order.indexOf(current);
        const next = order[(idx + 1) % order.length];
        select.value = next;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        updateHeaderThemeIcon(next);
      });
    }
    byId("currentAutoToggle").addEventListener("change", async (e)=>{
      await saveUiConfigPatch({ ui: { current_auto_refresh_enabled: !!e.target.checked } });
      resetTimer();
    });
    byId("currentIntervalInput").addEventListener("change", async ()=>{
      const v = Math.max(1, parseInt(byId("currentIntervalInput").value || "5", 10));
      byId("currentIntervalInput").value = String(v);
      await saveUiConfigPatch({ ui: { current_refresh_interval_sec: v } });
      resetTimer();
    });
    byId("allAutoToggle").addEventListener("change", async (e)=>{
      await saveUiConfigPatch({ ui: { all_auto_refresh_enabled: !!e.target.checked } });
      resetTimer();
    });
    byId("allIntervalInput").addEventListener("change", async ()=>{
      const v = Math.max(1, Math.min(60, parseInt(byId("allIntervalInput").value || "5", 10)));
      byId("allIntervalInput").value = String(v);
      await saveUiConfigPatch({ ui: { all_refresh_interval_min: v } });
      resetTimer();
    });
    initSteppers(document);
    setImportFileLabel("Choose a migration archive to review and import.");
    byId("addAccountBtn").addEventListener("click", async ()=>{
      pushOverlayLog("ui", "ui.click add_account");
      setError("");
      openAddDeviceModal({ reset:true });
    });
    byId("exportProfilesBtn").addEventListener("click", ()=>openExportProfilesModal());
    byId("importProfilesBtn").addEventListener("click", async ()=>{
      const warning = await openModal({
        title: "Import Profiles",
        body: "Imported data may grant account access and should only come from a trusted source. Keep exported files private, do not share them with other people, and use this feature at your own risk.\\n\\nContinue and choose an archive file?",
        okText: "Choose Archive",
        okClass: "btn-warning",
      });
      if(!warning || !warning.ok) return;
      byId("importProfilesInput").click();
    });
    byId("importProfilesInput").addEventListener("change", async (e)=>{
      const file = e?.target?.files && e.target.files[0] ? e.target.files[0] : null;
      if(!file) return;
      try{
        await runAction("local.import_profiles.analyze", ()=>startProfilesImportFlow(file), { skipRefresh:true });
      } finally {
        e.target.value = "";
      }
    });
    byId("addDeviceStartBtn").addEventListener("click", async ()=>{
      const name = getAddDeviceProfileName();
      if(!name) return;
      setError("");
      pushOverlayLog("ui", "ui.submit add_account.device", { profile: name });
      try{
        await startAddDeviceFlow(name);
      } catch(e){
        const msg = e?.message || String(e);
        setError(msg);
        pushOverlayLog("error", "device_auth.start_failed", { profile: name, error: msg });
        updateAddDeviceModal({ status:"failed", error: msg, message: msg, url: null, code: null });
      }
    });
    byId("addDeviceCopyBtn").addEventListener("click", async ()=>{
      const text = (addDeviceSessionState?.url || addDeviceSessionState?.code || "").trim();
      if(!text){ setError("No link/code available yet."); return; }
      try{
        const ok = await copyText(text);
        if(!ok){ setError("Failed to copy to clipboard."); return; }
        pushOverlayLog("ui", "device_auth.copy", { kind: addDeviceSessionState?.url ? "url" : "code" });
      } catch(e){
        setError("Failed to copy to clipboard.");
      }
    });
    byId("addDeviceOpenBtn").addEventListener("click", ()=>{
      const url = (addDeviceSessionState?.url || "").trim();
      if(!url){ setError("Login URL is not ready yet."); return; }
      window.open(url, "_blank", "noopener,noreferrer");
      pushOverlayLog("ui", "device_auth.open_browser");
    });
    byId("addDeviceLegacyBtn").addEventListener("click", async ()=>{
      const name = getAddDeviceProfileName();
      if(!name) return;
      if(addDeviceSessionId){
        try { await postApi("/api/local/add/cancel", { id: addDeviceSessionId }); } catch(_) {}
      }
      closeAddDeviceModal();
      pushOverlayLog("ui", "device_auth.fallback_normal_login", { profile: name });
      await runAction("local.add", ()=>postApi("/api/local/add", { name, timeout: 600, device_auth: false }));
    });
    byId("addDeviceCancelBtn").addEventListener("click", async ()=>{
      if(addDeviceSessionId){
        try { await postApi("/api/local/add/cancel", { id: addDeviceSessionId }); } catch(_) {}
      }
      closeAddDeviceModal();
    });
    const addDeviceNameInput = byId("addDeviceNameInput", false);
    if(addDeviceNameInput){
      addDeviceNameInput.addEventListener("input", () => {
        addDeviceProfileName = String(addDeviceNameInput.value || "").trim();
      });
      addDeviceNameInput.addEventListener("keydown", (e) => {
        if(e.key !== "Enter") return;
        e.preventDefault();
        byId("addDeviceStartBtn", false)?.click();
      });
    }
    const exportLogsBtn = byId("exportLogsBtn", false);
    if(exportLogsBtn) exportLogsBtn.addEventListener("click", exportDebugSnapshot);
    byId("removeAllBtn").addEventListener("click", async ()=>{
      const c1 = await openModal({ title:"Remove All Profiles", body:"Remove ALL saved profiles?\\n\\nThis cannot be undone." });
      if(!c1 || !c1.ok) return;
      const c2 = await openModal({ title:"Final Confirmation", body:"Delete all account profiles now?" });
      if(!c2 || !c2.ok) return;
      await runAction("local.remove_all", ()=>postApi("/api/local/remove-all", {}));
    });
    byId("colSettingsBtn").addEventListener("click", (e)=>{ e.stopPropagation(); openColumnsModal(); });
    byId("columnsDoneBtn").addEventListener("click", ()=>closeColumnsModal());
    byId("exportProfilesCancelBtn").addEventListener("click", ()=>closeExportProfilesModal());
    byId("exportProfilesConfirmBtn").addEventListener("click", ()=>runAction("local.export_profiles", ()=>startProfilesExportFlow(), { skipRefresh:true }));
    byId("exportSelectAllBtn").addEventListener("click", ()=>toggleAllExportProfiles(true));
    byId("exportUnselectAllBtn").addEventListener("click", ()=>toggleAllExportProfiles(false));
    byId("exportHeaderCheckbox").addEventListener("change", (e)=>toggleAllExportProfiles(!!e.target.checked));
    byId("columnsResetBtn").addEventListener("click", ()=>{
      columnPrefs = { ...defaultColumns };
      saveColumnPrefs();
      applyColumnVisibility();
      renderColumnsModal();
    });
    byId("importReviewCloseBtn").addEventListener("click", ()=>closeImportReviewModal());
    byId("importReviewCancelBtn").addEventListener("click", ()=>closeImportReviewModal());
    byId("importReviewApplyBtn").addEventListener("click", async ()=>{
      if(!importReviewState) return;
      const risky = (importReviewState.profiles || []).some((row) => row.action === "overwrite");
      if(risky){
        const confirmOverwrite = await openModal({
          title: "Confirm Import Apply",
          body: "One or more profiles will overwrite existing saved profiles. Keep exported data private, do not share it with other people, and use this feature at your own risk.\\n\\nApply this import now?",
          okText: "Apply Import",
          okClass: "btn-primary-danger",
        });
        if(!confirmOverwrite || !confirmOverwrite.ok) return;
      }
      await runAction("local.import_profiles.apply", async ()=>{
        const payload = await postApi("/api/local/import/apply", {
          analysis_id: importReviewState.analysis_id,
          profiles: importReviewState.profiles,
        });
        closeImportReviewModal();
        const summary = payload?.summary || {};
        showInAppNotice("Import Complete", `Imported ${summary.imported || 0}, skipped ${summary.skipped || 0}, overwritten ${summary.overwritten || 0}, failed ${summary.failed || 0}.`, { duration_ms: 9000 });
        await refreshAll({ showLoading:false, clearUsageCache:true });
      }, { skipRefresh:true });
    });
    byId("rowActionsCloseBtn").addEventListener("click", ()=>closeRowActionsModal());
    byId("rowActionsRenameBtn").addEventListener("click", async ()=>{
      const name = activeRowActionsName;
      closeRowActionsModal();
      if(!name) return;
      await renameProfileFlow(name);
    });
    byId("rowActionsRemoveBtn").addEventListener("click", async ()=>{
      const name = activeRowActionsName;
      closeRowActionsModal();
      if(!name) return;
      await removeProfileFlow(name);
    });
    byId("debugToggle").addEventListener("change", async ()=>{
      const on=!!byId("debugToggle").checked;
      await saveUiConfigPatch({ ui: { debug_mode: on } });
      updateHeaderDebugIcon(on);
      byId("debugRuntimeSection").style.display = on ? "block" : "none";
      if(on) await loadDebugLogs();
    });
    const debugBtn = byId("debugIconBtn", false);
    if(debugBtn){
      debugBtn.addEventListener("click", () => {
        const debugInput = byId("debugToggle");
        debugInput.checked = !debugInput.checked;
        debugInput.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    byId("alarmToggle").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { enabled: !!byId("alarmToggle").checked } }).catch((e)=>setError(e?.message || String(e))));
    byId("alarm5h").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { thresholds: { h5_warn_pct: Math.max(0, Math.min(100, parseInt(byId("alarm5h").value || "20", 10))) } } }).catch((e)=>setError(e?.message || String(e))));
    byId("alarmWeekly").addEventListener("change", ()=> saveUiConfigPatch({ notifications: { thresholds: { weekly_warn_pct: Math.max(0, Math.min(100, parseInt(byId("alarmWeekly").value || "20", 10))) } } }).catch((e)=>setError(e?.message || String(e))));
    byId("testAlarmBtn").addEventListener("click", async ()=>{
      try{
        await runNativeNotificationTest();
      } catch(e){
        setError(e?.message || String(e));
      }
    });
    byId("asEnabled").addEventListener("change", async ()=>{
      const next = !!byId("asEnabled").checked;
      const rankingNow = String(byId("asRanking", false)?.value || latestData?.config?.auto_switch?.ranking_mode || "balanced");
      updateRankingModeUI(rankingNow, next);
      pendingAutoSwitchEnabled = next;
      try{
        await runAction("auto_switch.enable", ()=>postApi("/api/auto-switch/enable", { enabled: next }));
      } finally {
        pendingAutoSwitchEnabled = null;
      }
    });
    byId("asRunSwitchBtn").addEventListener("click", async ()=>{
      if(autoSwitchRunActionInFlight) return;
      autoSwitchRunActionInFlight = true;
      renderAutoSwitchActionButtons();
      try{
        await runAction("auto_switch.run_switch", ()=>postApi("/api/auto-switch/run-switch", {}));
      } finally {
        autoSwitchRunActionInFlight = false;
        renderAutoSwitchActionButtons();
      }
    });
    byId("asRapidTestBtn").addEventListener("click", async ()=>{
      if(autoSwitchRapidActionInFlight) return;
      autoSwitchRapidActionInFlight = true;
      renderAutoSwitchActionButtons();
      try{
        await runAction("auto_switch.rapid_test", ()=>postApi("/api/auto-switch/rapid-test", {}));
      } finally {
        autoSwitchRapidActionInFlight = false;
        renderAutoSwitchActionButtons();
      }
    });
    byId("asForceStopBtn").addEventListener("click", ()=> runAction("auto_switch.stop_tests", ()=>postApi("/api/auto-switch/stop-tests", {})));
    byId("asTestAutoSwitchBtn").addEventListener("click", async ()=>{
      const ask = await openModal({
        title: "Test Auto Switch",
        body: "Temporary 5H threshold % for test (optional). Leave empty to use current value.",
        input: true,
        inputPlaceholder: "e.g. 59",
      });
      if(!ask || !ask.ok) return;
      const raw = String(ask.value || "").trim();
      let threshold = null;
      if(raw){
        const n = parseInt(raw, 10);
        if(!Number.isFinite(n)){
          setError("Test threshold must be a number.");
          return;
        }
        threshold = Math.max(0, Math.min(100, n));
      }
      const btn = byId("asTestAutoSwitchBtn", false);
      const prevTxt = btn ? btn.textContent : "";
      if(btn){
        btn.disabled = true;
        btn.textContent = "Testing...";
      }
      setError("");
      try{
        const data = await postApi("/api/auto-switch/test", {
          threshold_5h: threshold,
          timeout_sec: 30,
        });
        const used = data?.used_threshold_5h;
        const switched = !!data?.switched;
        let body = `Used 5H threshold: ${used ?? "(current)"}%\\nTimeout: ${data?.timeout_sec ?? 30}s`;
        if(switched){
          const ev = data?.event || {};
          body += `\\n\\nResult: switched\\nEvent: ${ev.message || "auto-switched"}`;
        } else {
          body += `\\n\\nResult: no switch event within timeout.\\nCheck System.Out for warning/no-candidate details.`;
        }
        await openModal({ title: "Auto Switch Test Result", body });
      } catch(e){
        setError(e?.message || String(e));
      } finally {
        if(btn){
          btn.disabled = false;
          btn.textContent = prevTxt || "Test Auto Switch";
        }
      }
    });
    byId("asChainEditBtn").addEventListener("click", ()=>openChainEditModal());
    byId("chainEditCancelBtn").addEventListener("click", ()=>closeChainEditModal());
    byId("chainEditSaveBtn").addEventListener("click", async ()=>{
      setError("");
      const startedAt = Date.now();
      const payloadChain = ensureLockedChainOrder(chainEditNames);
      const saveBtn = byId("chainEditSaveBtn", false);
      const cancelBtn = byId("chainEditCancelBtn", false);
      const chainBox = byId("asChainPreview", false);
      const prevSaveTxt = saveBtn ? saveBtn.textContent : "";
      if(saveBtn){
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";
      }
      if(cancelBtn) cancelBtn.disabled = true;
      if(chainBox) chainBox.style.opacity = "0.55";
      pushOverlayLog("ui", "action.start auto_switch.chain.save");
      try{
        await postApi("/api/auto-switch/chain", { chain: payloadChain });
        const rankingEl = byId("asRanking", false);
        if(rankingEl){
          rankingEl.value = "manual";
          rankingEl.dataset.dirty = "0";
        }
        if(latestData?.config?.auto_switch){
          latestData.config.auto_switch.ranking_mode = "manual";
        }
        updateRankingModeUI("manual", !!byId("asEnabled", false)?.checked);
        const liveChain = await safeGet("/api/auto-switch/chain");
        if(liveChain && !liveChain.__error){
          latestData.autoChain = liveChain;
          renderChainPreview(liveChain);
        } else {
          const fallbackPayload = {
            chain: payloadChain,
            items: payloadChain.map((n)=>({ name:n, remaining_5h:null, remaining_weekly:null })),
            manual_chain: payloadChain,
            chain_text: payloadChain.join(" -> ") || "-",
          };
          latestData.autoChain = fallbackPayload;
          renderChainPreview(fallbackPayload);
        }
        closeChainEditModal();
        pushOverlayLog("ui", "action.success auto_switch.chain.save", { duration_ms: Date.now() - startedAt });
        setTimeout(()=>{ refreshAll().catch(()=>{}); }, 0);
      } catch(e){
        const msg = e?.message || String(e);
        pushOverlayLog("error", "action.fail auto_switch.chain.save", { error: msg, duration_ms: Date.now() - startedAt });
        setError(msg);
      } finally {
        if(chainBox) chainBox.style.opacity = "";
        if(saveBtn){
          saveBtn.disabled = false;
          saveBtn.textContent = prevSaveTxt || "Save";
        }
        if(cancelBtn) cancelBtn.disabled = false;
      }
    });
    const saveAutoSwitchTiming = async () => {
      if(autoSwitchTimingSaveTimer){
        clearTimeout(autoSwitchTimingSaveTimer);
        autoSwitchTimingSaveTimer = null;
      }
      const cfgAuto = latestData?.config?.auto_switch || {};
      const delay = intOrDefault(byId("asDelay").value, cfgAuto.delay_sec ?? 60, 0, 3600);
      byId("asDelay").value = String(delay);
      try{
        await saveUiConfigPatch({ auto_switch: { delay_sec: delay } });
        if(latestData?.config?.auto_switch){
          latestData.config.auto_switch.delay_sec = delay;
        }
        const d1 = byId("asDelay", false);
        if(d1) d1.dataset.dirty = "0";
      } catch(e){
        setError(e?.message || String(e));
      }
    };
    const scheduleAutoSwitchTimingSave = () => {
      if(autoSwitchTimingSaveTimer) clearTimeout(autoSwitchTimingSaveTimer);
      autoSwitchTimingSaveTimer = setTimeout(() => {
        autoSwitchTimingSaveTimer = null;
        saveAutoSwitchTiming();
      }, 320);
    };
    ["asDelay"].forEach((id) => {
      const el = byId(id, false);
      if(!el) return;
      el.addEventListener("input", scheduleAutoSwitchTimingSave);
      el.addEventListener("change", saveAutoSwitchTiming);
    });
    const saveSelectionPolicy = async () => {
      if(autoSwitchPolicySaveTimer){
        clearTimeout(autoSwitchPolicySaveTimer);
        autoSwitchPolicySaveTimer = null;
      }
      const cfgAuto = latestData?.config?.auto_switch || {};
      const cfgThr = cfgAuto.thresholds || {};
      const patch = {
        auto_switch: {
          ranking_mode: byId("asRanking").value || (cfgAuto.ranking_mode || "balanced"),
          thresholds: {
            h5_switch_pct: intOrDefault(byId("as5h").value, cfgThr.h5_switch_pct ?? 20, 0, 100),
            weekly_switch_pct: intOrDefault(byId("asWeekly").value, cfgThr.weekly_switch_pct ?? 20, 0, 100),
          },
        },
      };
      await saveUiConfigPatch(patch);
      if(latestData?.config?.auto_switch){
        latestData.config.auto_switch.ranking_mode = patch.auto_switch.ranking_mode;
        latestData.config.auto_switch.thresholds = {
          ...(latestData.config.auto_switch.thresholds || {}),
          ...patch.auto_switch.thresholds,
        };
      }
      ["as5h","asWeekly","asRanking"].forEach((id) => {
        const el = byId(id, false);
        if(el) el.dataset.dirty = "0";
      });
    };
    const scheduleSelectionPolicySave = () => {
      if(autoSwitchPolicySaveTimer) clearTimeout(autoSwitchPolicySaveTimer);
      autoSwitchPolicySaveTimer = setTimeout(() => {
        autoSwitchPolicySaveTimer = null;
        saveSelectionPolicy().catch((e)=>setError(e?.message || String(e)));
      }, 320);
    };
    ["as5h","asWeekly"].forEach((id) => {
      const el = byId(id, false);
      if(!el) return;
      el.addEventListener("input", scheduleSelectionPolicySave);
      el.addEventListener("change", ()=>saveSelectionPolicy().catch((e)=>setError(e?.message || String(e))));
    });
    const rankingEl = byId("asRanking", false);
    if(rankingEl){
      rankingEl.addEventListener("change", ()=>{
        updateRankingModeUI(rankingEl.value, !!byId("asEnabled", false)?.checked);
        saveSelectionPolicy().catch((e)=>setError(e?.message || String(e)));
      });
    }
    byId("asAutoArrangeBtn").addEventListener("click", async ()=>{
      const rankingEl = byId("asRanking", false);
      if(rankingEl) rankingEl.value = "balanced";
      updateRankingModeUI("balanced", !!byId("asEnabled", false)?.checked);
      const btn = byId("asAutoArrangeBtn", false);
      const prevTxt = btn ? btn.textContent : "";
      setError("");
      if(btn){
        btn.disabled = true;
        btn.textContent = "Arranging...";
      }
      try{
        if(autoSwitchPolicySaveTimer){
          clearTimeout(autoSwitchPolicySaveTimer);
          autoSwitchPolicySaveTimer = null;
        }
        await saveSelectionPolicy();
        const data = await postApi("/api/auto-switch/auto-arrange", {});
        const names = Array.isArray(data?.chain) ? data.chain : [];
        const items = Array.isArray(data?.items) ? data.items : [];
        const payload = {
          chain: names,
          items,
          manual_chain: Array.isArray(data?.manual_chain) ? data.manual_chain : names,
          chain_text: String(data?.chain_text || names.join(" -> ") || "-"),
        };
        latestData.autoChain = payload;
        renderChainPreview(payload);
        setTimeout(()=>{ refreshAll().catch(()=>{}); }, 0);
      } catch(e){
        setError(e?.message || String(e));
      } finally {
        if(btn){
          btn.disabled = false;
          btn.textContent = prevTxt || "Auto Arrange";
        }
      }
    });
    ["asDelay","as5h","asWeekly","asRanking"].forEach((id) => {
      const el = byId(id, false);
      if(!el) return;
      const markDirty = () => { el.dataset.dirty = "1"; };
      el.addEventListener("input", markDirty);
      el.addEventListener("change", markDirty);
    });
    byId("advStatusBtn").addEventListener("click", ()=>runAction("adv.status", ()=>callApi("/api/adv/status")));
    byId("advListBtn").addEventListener("click", ()=>runAction("adv.list", ()=>callApi("/api/adv/list?debug="+(byId("advListDebug").checked?"1":"0"))));
    byId("advLoginBtn").addEventListener("click", ()=>runAction("adv.login", ()=>postApi("/api/adv/login",{device_auth:byId("advLoginDevice").checked})));
    byId("advSwitchBtn").addEventListener("click", ()=>runAction("adv.switch", ()=>postApi("/api/adv/switch",{query:byId("advQuery").value.trim()})));
    byId("advRemoveBtn").addEventListener("click", ()=>runAction("adv.remove", ()=>postApi("/api/adv/remove",{query:byId("advQuery").value.trim(), all:byId("advRemoveAll").checked})));
    byId("advConfigBtn").addEventListener("click", ()=>runAction("adv.config", ()=>postApi("/api/adv/config",{scope:byId("advScope").value, action:byId("advAction").value, threshold_5h:byId("adv5h").value.trim()||null, threshold_weekly:byId("advWeekly").value.trim()||null})));
    byId("advImportBtn").addEventListener("click", ()=>runAction("adv.import", ()=>postApi("/api/adv/import",{path:byId("advImportPath").value.trim(), alias:byId("advImportAlias").value.trim(), cpa:byId("advImportCpa").checked, purge:byId("advImportPurge").checked})));
    byId("advDaemonOnceBtn").addEventListener("click", ()=>runAction("adv.daemon.once", ()=>postApi("/api/adv/daemon",{mode:"once"})));
    byId("advDaemonWatchBtn").addEventListener("click", ()=>runAction("adv.daemon.watch", ()=>postApi("/api/adv/daemon",{mode:"watch"})));
    byId("advCleanBtn").addEventListener("click", ()=>runAction("adv.clean", ()=>postApi("/api/adv/clean",{})));
    byId("advAuthBtn").addEventListener("click", ()=>runAction("adv.auth", ()=>postApi("/api/adv/auth",{args:byId("advAuthArgs").value.trim(), timeout:60})));
    byId("modalCancelBtn").addEventListener("click", ()=>modalCancelAction());
    byId("modalOkBtn").addEventListener("click", ()=>modalOkAction());
    byId("appUpdateCancelBtn").addEventListener("click", ()=>closeUpdateModal());
    byId("appUpdateConfirmBtn").addEventListener("click", ()=>runAppUpdateFlow().catch((e)=>setError(e?.message || String(e))));
    byId("modalBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("modalBackdrop")) closeModal({ ok:false }); });
    byId("appUpdateBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("appUpdateBackdrop")) closeUpdateModal(); });
    byId("addDeviceBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("addDeviceBackdrop")) closeAddDeviceModal(); });
    byId("exportProfilesBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("exportProfilesBackdrop")) closeExportProfilesModal(); });
    byId("rowActionsBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("rowActionsBackdrop")) closeRowActionsModal(); });
    byId("chainEditBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("chainEditBackdrop")) closeChainEditModal(); });
    byId("importReviewBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("importReviewBackdrop")) closeImportReviewModal(); });
    document.addEventListener("keydown", (e)=>{
      const chainEditBackdrop = byId("chainEditBackdrop", false);
      if(chainEditBackdrop && chainEditBackdrop.style.display === "flex" && e.key === "Escape"){
        e.preventDefault();
        closeChainEditModal();
        return;
      }
      const importReviewBackdrop = byId("importReviewBackdrop", false);
      if(importReviewBackdrop && importReviewBackdrop.style.display === "flex" && e.key === "Escape"){
        e.preventDefault();
        closeImportReviewModal();
        return;
      }
      const exportProfilesBackdrop = byId("exportProfilesBackdrop", false);
      if(exportProfilesBackdrop && exportProfilesBackdrop.style.display === "flex" && e.key === "Escape"){
        e.preventDefault();
        closeExportProfilesModal();
        return;
      }
      const appUpdateBackdrop = byId("appUpdateBackdrop", false);
      if(appUpdateBackdrop && appUpdateBackdrop.style.display === "flex" && e.key === "Escape"){
        e.preventDefault();
        closeUpdateModal();
        return;
      }
      const backdrop = byId("modalBackdrop", false);
      if(!backdrop || backdrop.style.display !== "flex") return;
      if(e.key === "Escape"){
        e.preventDefault();
        modalCancelAction();
        return;
      }
      if(e.key === "Enter"){
        const t = e.target;
        if(t && (t.tagName === "TEXTAREA")) return;
        e.preventDefault();
        modalOkAction();
      }
    });
    byId("columnsModalBackdrop").addEventListener("click", (e)=>{ if(e.target === byId("columnsModalBackdrop")) closeColumnsModal(); });
    applyAppUpdateStatus({ update_available: false, latest_version: "", current_version: `v${UI_VERSION}` });
    renderColumnsModal();
    updateExportSelectedSummary();
    applyColumnVisibility();
    initSteppers(document);
    renderSortIndicators();
    const bootSnapshot = loadBootSnapshot();
    if(bootSnapshot && typeof bootSnapshot === "object"){
      if(bootSnapshot.config && !latestData.config){
        latestData.config = bootSnapshot.config;
        applyConfigToControls(bootSnapshot.config);
        renderColumnsModal();
        applyColumnVisibility();
      }
      if(bootSnapshot.usage && !latestData.usage){
        latestData.usage = bootSnapshot.usage;
        renderTable(bootSnapshot.usage);
      }
    }
    document.querySelectorAll("th[data-sort]").forEach(th => th.addEventListener("click", ()=>{
      const key=th.dataset.sort;
      if(sortState.key===key) sortState.dir=sortState.dir==="asc"?"desc":"asc";
      else sortState={key,dir:"desc"};
      localStorage.setItem("codex_sort_state", JSON.stringify(sortState));
      renderSortIndicators();
      if(latestData.usage) renderTable(latestData.usage);
    }));
    await refreshAll({ showLoading: true, clearUsageCache: true });
    await loadAppUpdateStatus(false);
    resetTimer();
    resetRemainTicker();
    resetAutoSwitchStateTimer();
    eventsTimer = setInterval(async ()=>{
      const eventsPayload = await safeGet("/api/events?since_id="+encodeURIComponent(String(lastEventId)));
      if(eventsPayload.__error) return;
      const incoming = eventsPayload.events || [];
      if(incoming.length){
        for(const ev of incoming){
          await maybeNotify(ev);
          lastEventId = Math.max(lastEventId, Number(ev.id || 0));
          latestData.events.push(ev);
          pushOverlayLog("event", `${ev.type || "event"}: ${ev.message || ""}`, ev.details || null);
          if(ev.type === "switch"){
            await animateSwitchFromEvent(ev);
          }
        }
        renderEvents(latestData.events);
      }
    }, 1500);
    window.__camBootState.booted = true;
    window.__camBootState.lastError = null;
    window.__camBootState.ts = Date.now();
  } catch(e) {
    window.__camBootState.booted = false;
    window.__camBootState.lastError = e?.message || String(e);
    window.__camBootState.ts = Date.now();
    showFatal(e);
  }
}
init();
