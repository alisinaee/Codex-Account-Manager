import React, { useEffect, useState } from "react";
import Button from "./components/Button.jsx";
import { SettingCopy, SettingsCardShell, SettingsSubsection } from "./components/SettingsCardShell.jsx";
import StepperInput from "./components/StepperInput.jsx";
import ToggleSwitch from "./components/ToggleSwitch.jsx";

function LabelValueRow({ label, value }) {
  return (
    <div className="kv-row">
      <span className="kv-label">{label}</span>
      <div className="kv-value">{value}</div>
    </div>
  );
}

function AutoRefreshSettingsCard({ state, onSavePatch }) {
  const ui = state?.config?.ui || {};

  return (
    <SettingsCardShell
      title="Refresh rules"
      description="Control automatic usage refresh timing without changing profile data."
      className="settings-card-refresh"
      testId="settings-card-refresh"
    >
      <div className="settings-subsection-stack">
        <SettingsSubsection title="Current account refresh" meta="Seconds">
          <div className="setting-row">
            <SettingCopy label="Enabled" helper="Refresh the active account usage automatically." />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!ui.current_auto_refresh_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { current_auto_refresh_enabled: nextValue } })}
                ariaLabel="Enable current account refresh"
              />
            </div>
          </div>
          <div className="setting-row">
            <SettingCopy label="Delay" helper="Recommended for near-real-time status." />
            <div className="setting-control">
              <StepperInput
                value={ui.current_refresh_interval_sec ?? 5}
                min={1}
                max={3600}
                unit="sec"
                onChange={(value) => onSavePatch({ ui: { current_refresh_interval_sec: value } })}
              />
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="All accounts refresh" meta="Minutes">
          <div className="setting-row">
            <SettingCopy label="Enabled" helper="Refresh every stored account usage in the background." />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!ui.all_auto_refresh_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { all_auto_refresh_enabled: nextValue } })}
                ariaLabel="Enable all accounts refresh"
              />
            </div>
          </div>
          <div className="setting-row">
            <SettingCopy label="Delay" helper="Use a longer interval to reduce background churn." />
            <div className="setting-control">
              <StepperInput
                value={ui.all_refresh_interval_min ?? 5}
                min={1}
                max={60}
                unit="min"
                onChange={(value) => onSavePatch({ ui: { all_refresh_interval_min: value } })}
              />
            </div>
          </div>
        </SettingsSubsection>
      </div>
    </SettingsCardShell>
  );
}

function NotificationsSettingsCard({ state, onNotify, onSavePatch }) {
  const notifications = state?.config?.notifications || {};

  return (
    <SettingsCardShell
      title="Notifications"
      description="Choose when the desktop shell should warn you about usage thresholds."
      className="settings-card-notifications"
      testId="settings-card-notifications"
      footer={<Button onClick={onNotify}>Test notification</Button>}
    >
      <div className="settings-subsection-stack">
        <SettingsSubsection title="Desktop notifications">
          <div className="setting-row">
            <SettingCopy label="Enabled" helper="Show native desktop alerts when usage thresholds are reached." />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!notifications.enabled}
                onChange={(nextValue) => onSavePatch({ notifications: { enabled: nextValue } })}
                ariaLabel="Enable notifications"
              />
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="5h warning threshold" meta="Percent">
          <div className="setting-row">
            <SettingCopy label="Warning threshold" helper="Warn when the remaining five-hour balance is getting low." />
            <div className="setting-control">
              <StepperInput
                value={notifications.thresholds?.h5_warn_pct ?? 20}
                min={0}
                max={100}
                onChange={(value) => onSavePatch({ notifications: { thresholds: { h5_warn_pct: value } } })}
              />
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="Weekly warning threshold" meta="Percent">
          <div className="setting-row">
            <SettingCopy label="Warning threshold" helper="Warn when the weekly balance approaches the selected percentage." />
            <div className="setting-control">
              <StepperInput
                value={notifications.thresholds?.weekly_warn_pct ?? 20}
                min={0}
                max={100}
                onChange={(value) => onSavePatch({ notifications: { thresholds: { weekly_warn_pct: value } } })}
              />
            </div>
          </div>
        </SettingsSubsection>
      </div>
    </SettingsCardShell>
  );
}

function WindowsIntegrationSettingsCard({ ui, displayTargets, onSavePatch }) {
  return (
    <SettingsCardShell
      title="Windows integration"
      description="Surface usage status in native Windows affordances without changing the core controls."
      className="settings-card-windows"
      testId="settings-card-windows"
    >
      <div className="settings-subsection-stack">
        <SettingsSubsection title="Taskbar usage badge">
          <div className="setting-row">
            <SettingCopy
              label="Enabled"
              helper="Add a compact usage badge to the Windows taskbar button."
              title="5h means the five-hour usage window."
            />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!ui.windows_taskbar_usage_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { windows_taskbar_usage_enabled: nextValue } })}
                ariaLabel="Show current 5h usage on taskbar"
              />
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="Mini live usage meter">
          <div className="setting-row">
            <SettingCopy
              label="Enabled"
              helper="Keep a small always-on-top usage meter near the taskbar tray area."
              title="Floating meter stays near the Windows tray and updates continuously."
            />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!ui.windows_mini_meter_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { windows_mini_meter_enabled: nextValue } })}
                ariaLabel="Show mini live usage meter near tray"
              />
            </div>
          </div>
          <div className="setting-row">
            <SettingCopy label="Allow drag move" helper="Let users reposition the mini meter when it is visible." />
            <div className="setting-control">
              <ToggleSwitch
                checked={!!ui.windows_mini_meter_drag_enabled}
                onChange={(nextValue) => onSavePatch({ ui: { windows_mini_meter_drag_enabled: nextValue } })}
                ariaLabel="Allow drag move mini meter"
              />
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="Mini meter display target">
          <div className="setting-row">
            <SettingCopy label="Display target" helper="Choose which display the mini meter should follow." />
            <div className="setting-control settings-select-control">
              <select
                value={String(
                  ui.windows_mini_meter_display_target
                    || (ui.windows_mini_meter_display_mode === "primary" ? "primary" : "follow_focus"),
                ).trim().toLowerCase()}
                onChange={(event) => onSavePatch({
                  ui: {
                    windows_mini_meter_display_target: event.target.value,
                    windows_mini_meter_display_mode: event.target.value === "primary" ? "primary" : "follow_focus",
                  },
                })}
                disabled={!ui.windows_mini_meter_enabled}
              >
                <option value="follow_focus">Follow focused screen</option>
                <option value="primary">Pin to primary screen</option>
                {displayTargets.map((display) => (
                  <option key={display.id} value={`display:${display.id}`}>
                    {display.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </SettingsSubsection>

        <SettingsSubsection title="Mini meter font size" meta="Pixels">
          <div className="setting-row">
            <SettingCopy label="Font size" helper="Adjust text size for readability on the floating meter." />
            <div className="setting-control">
              <StepperInput
                value={ui.windows_mini_meter_font_size ?? 14}
                min={10}
                max={24}
                onChange={(value) => onSavePatch({ ui: { windows_mini_meter_font_size: value } })}
              />
            </div>
          </div>
        </SettingsSubsection>
      </div>
    </SettingsCardShell>
  );
}

export function SystemInfoSettingsCard({ platformName, ui }) {
  return (
    <SettingsCardShell
      title="System info"
      description="Quick status summary for the current desktop shell configuration."
      className="settings-card-system"
      testId="settings-card-system"
    >
      <div className="settings-subsection-stack">
        <SettingsSubsection title="Desktop shell">
          <LabelValueRow label="Platform" value={platformName} />
        </SettingsSubsection>
        <SettingsSubsection title="Current refresh status">
          <LabelValueRow label="Current refresh" value={ui.current_auto_refresh_enabled ? `${ui.current_refresh_interval_sec || 5}s` : "disabled"} />
        </SettingsSubsection>
        <SettingsSubsection title="All accounts refresh status">
          <LabelValueRow label="All refresh" value={ui.all_auto_refresh_enabled ? `${ui.all_refresh_interval_min || 5}m` : "disabled"} />
        </SettingsSubsection>
      </div>
    </SettingsCardShell>
  );
}

function SettingsView({ state, onNotify, onSavePatch }) {
  const ui = state?.config?.ui || {};
  const isWindows = window.codexAccountDesktop?.platform === "win32";
  const [displayTargets, setDisplayTargets] = useState([]);
  const desktop = window.codexAccountDesktop;

  useEffect(() => {
    let cancelled = false;
    if (!isWindows || !desktop?.listDisplays) {
      setDisplayTargets([]);
      return () => {
        cancelled = true;
      };
    }
    desktop.listDisplays()
      .then((items) => {
        if (cancelled) return;
        const next = Array.isArray(items) ? items.filter((row) => Number.isFinite(Number(row?.id))) : [];
        setDisplayTargets(next);
      })
      .catch(() => {
        if (!cancelled) setDisplayTargets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [desktop, isWindows]);

  return (
    <section className="view settings-view scrollable" data-testid="settings-view">
      <div className="settings-layout">
        <div className="settings-card-stack settings-card-stack-main">
          <AutoRefreshSettingsCard state={state} onSavePatch={onSavePatch} />
          <NotificationsSettingsCard state={state} onNotify={onNotify} onSavePatch={onSavePatch} />
          {isWindows ? (
            <WindowsIntegrationSettingsCard ui={ui} displayTargets={displayTargets} onSavePatch={onSavePatch} />
          ) : null}
        </div>
      </div>
    </section>
  );
}

export default SettingsView;
