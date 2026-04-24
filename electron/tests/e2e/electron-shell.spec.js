const { test, expect, _electron: electron } = require("@playwright/test");

async function quitApp(app) {
  await app.evaluate(async ({ app: electronApp }) => {
    electronApp.isQuitting = true;
    electronApp.quit();
  }).catch(() => {});
  await app.close().catch(() => {});
}

test("launches the Electron shell and exposes the desktop preload bridge", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_SKIP_BACKEND: "1",
      CAM_ELECTRON_DISABLE_TRAY: "1",
    },
  });

  const window = await app.firstWindow();
  await expect(window.getByTestId("electron-renderer")).toBeVisible();
  await expect(window.getByTestId("profiles-view")).toBeVisible();
  await expect(window.locator(".btn-primary").first()).toBeVisible();
  await expect(window.locator(".usage-meter").first()).toBeVisible();
  await expect.poll(() => window.evaluate(() => window.codexAccountDesktop?.shell)).toBe("electron");

  const title = await app.evaluate(async ({ app: electronApp }) => electronApp.getName());
  expect(title).toBe("Codex Account Manager");

  await quitApp(app);
});

test("desktop switch bridge keeps the Electron app running", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_SKIP_BACKEND: "1",
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_MOCK_SWITCH_DELAY_MS: "250",
    },
  });

  const window = await app.firstWindow();
  await expect(window.getByTestId("profiles-view")).toBeVisible();
  await window.locator("tbody tr", { hasText: "backup" }).getByRole("button", { name: "Switch" }).click();

  await expect(window.locator("tr.switch-row-pending")).toBeVisible();
  await expect(window.locator("tbody button.btn-progress")).toBeVisible();
  await expect(window.locator("tr.current-row").filter({ hasText: "backup" })).toBeVisible();
  expect(app.windows().length).toBeGreaterThan(0);

  await quitApp(app);
});

test("sidebar toggles and settings stay separate from profiles", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_SKIP_BACKEND: "1",
      CAM_ELECTRON_DISABLE_TRAY: "1",
    },
  });

  const window = await app.firstWindow();
  const sidebar = window.getByTestId("desktop-sidebar");
  await expect(sidebar).toHaveClass(/fixed|minimal/);

  await window.getByRole("button", { name: /Collapse sidebar|Expand sidebar/ }).click();
  await expect(sidebar).toHaveClass(/minimal|fixed/);
  await window.getByTestId("sidebar-expand-hitarea").click();
  await expect(sidebar).toHaveClass(/fixed/);
  await window.getByRole("button", { name: /Collapse sidebar|Expand sidebar/ }).click();
  await expect(sidebar).toHaveClass(/minimal/);
  await window.locator('nav button[title="Settings"]').click();
  await expect(window.getByTestId("settings-view")).toBeVisible();
  await expect(window.getByTestId("profiles-view")).toHaveCount(0);

  await quitApp(app);
});

test("electron renderer exposes the web panel parity surfaces", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_SKIP_BACKEND: "1",
      CAM_ELECTRON_DISABLE_TRAY: "1",
    },
  });

  const window = await app.firstWindow();
  await expect(window.getByRole("button", { name: "Columns" })).toBeVisible();
  await expect(window.getByRole("button", { name: /Auto Refresh/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Guide & Help/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Update/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Debug/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Usage/i })).toHaveCount(0);
  await expect(window.getByTestId("sidebar-current-profile")).toContainText("work");
  await expect(window.getByTestId("sidebar-current-profile")).toContainText("work@example.test");

  await window.getByRole("button", { name: "Auto Refresh" }).click();
  await expect(window.getByTestId("auto-refresh-view")).toBeVisible();
  await expect(window.getByTestId("auto-refresh-view").getByText("Current Account Auto Refresh", { exact: true }).first()).toBeVisible();
  await expect(window.getByTestId("auto-refresh-view").getByText("Auto Refresh All", { exact: true }).first()).toBeVisible();

  await window.getByRole("button", { name: "Auto Switch" }).click();
  await expect(window.getByTestId("autoswitch-view")).toBeVisible();
  await expect(window.getByText("Auto-Switch Rules")).toBeVisible();
  await expect(window.getByText("Switch Chain Preview")).toBeVisible();

  await window.getByTestId("desktop-sidebar").getByRole("button", { name: "Settings" }).click();
  await expect(window.getByText("Appearance")).toBeVisible();
  await expect(window.getByText("Maintenance")).toBeVisible();

  await window.getByRole("button", { name: "Profiles" }).click();
  await expect(window.getByRole("button", { name: /Add Account/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Remove All/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Columns/i })).toBeVisible();
  await expect(window.locator("button[aria-label*='row actions' i], button[title*='row actions' i], button[data-row-actions]").first()).toBeVisible();
  await expect(window.locator("td[data-col='email']").first()).toHaveText("work@example.test");
  await expect.poll(() => window.locator(".profiles-table-wrap").evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  await window.setViewportSize({ width: 920, height: 700 });
  await expect(window.getByTestId("profiles-mobile-list")).toBeVisible();
  await expect(window.locator(".profiles-table-wrap table")).toBeHidden();

  await quitApp(app);
});
