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
  await expect(window.locator(".usage-bar-track").first()).toBeVisible();
  await expect.poll(() => window.evaluate(() => window.codexAccountDesktop?.shell)).toBe("electron");

  const title = await app.evaluate(async ({ app: electronApp }) => electronApp.getName());
  expect(title).toBe("Codex Account Manager");

  await quitApp(app);
});

test("shows the runtime setup screen when the Python core is missing", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_RUNTIME_FIXTURE: JSON.stringify({
        phase: "core_missing",
        python: { available: true, supported: true, version: "3.11.9", path: "/usr/bin/python3" },
        core: { installed: false, version: "", commandPath: "" },
        uiService: { running: false, healthy: false, host: "127.0.0.1", port: 4673, baseUrl: "http://127.0.0.1:4673/", token: "" },
        errors: [{ code: "CORE_MISSING", message: "Codex Account Manager core is not installed." }],
      }),
    },
  });

  const window = await app.firstWindow();
  await expect(window.getByTestId("runtime-setup-view")).toBeVisible();
  await expect(window.getByRole("heading", { name: /set up python core/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /install core/i })).toBeVisible();
  await expect(window.getByTestId("runtime-details")).toHaveCount(0);

  const pageFitsViewport = await window.evaluate(() => {
    const node = document.scrollingElement || document.documentElement;
    return node.scrollHeight <= node.clientHeight;
  });
  expect(pageFitsViewport).toBe(true);

  await quitApp(app);
});

test("runtime setup view contains long bootstrap errors without page scroll", async () => {
  const verboseErrors = Array.from({ length: 120 }, (_, index) => ({
    code: `CORE_INSTALL_FAILED_${index + 1}`,
    message: `error line ${index + 1}: externally managed environment blocked bootstrap install`,
  }));
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_RUNTIME_FIXTURE: JSON.stringify({
        phase: "error",
        reason: "core_install_failed",
        message: "Codex Account Manager core install failed.",
        python: { available: true, supported: true, version: "3.14.4", path: "/opt/homebrew/bin/python3" },
        core: { installed: false, version: "", commandPath: "" },
        uiService: { running: false, healthy: false, host: "127.0.0.1", port: 4673, baseUrl: "http://127.0.0.1:4673/", token: "" },
        errors: verboseErrors,
      }),
    },
  });

  const window = await app.firstWindow();
  await window.setViewportSize({ width: 820, height: 720 });
  await window.getByTestId("runtime-details-toggle").click();
  const scroller = window.getByTestId("runtime-details-body");
  await expect(scroller).toBeVisible();
  const scrollState = await scroller.evaluate((node) => {
    const overflows = node.scrollHeight > node.clientHeight + 1;
    node.style.scrollBehavior = "auto";
    node.scrollTop = node.scrollHeight;
    return { overflows, canScroll: node.scrollTop > 0 };
  });
  expect(scrollState.overflows ? scrollState.canScroll : true).toBe(true);
  await expect(window.getByRole("button", { name: /Install Core/i })).toBeVisible();

  await quitApp(app);
});

test("runtime setup view uses the available width on wide windows when details are open", async () => {
  const verboseErrors = Array.from({ length: 120 }, (_, index) => ({
    code: `CORE_INSTALL_FAILED_${index + 1}`,
    message: `error line ${index + 1}: externally managed environment blocked bootstrap install`,
  }));
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_RUNTIME_FIXTURE: JSON.stringify({
        phase: "error",
        reason: "core_install_failed",
        message: "Codex Account Manager core install failed.",
        python: { available: true, supported: true, version: "3.14.4", path: "/opt/homebrew/bin/python3" },
        core: { installed: false, version: "", commandPath: "" },
        uiService: { running: false, healthy: false, host: "127.0.0.1", port: 4673, baseUrl: "http://127.0.0.1:4673/", token: "" },
        errors: verboseErrors,
      }),
    },
  });

  const window = await app.firstWindow();
  await window.setViewportSize({ width: 1560, height: 940 });
  await window.getByTestId("runtime-details-toggle").click();
  await expect(window.getByTestId("runtime-progress-bar")).toBeVisible();
  await expect(window.getByTestId("runtime-progress-label")).toContainText("%");

  const layout = await window.getByTestId("runtime-card").evaluate((node) => {
    const bounds = node.getBoundingClientRect();
    return {
      width: bounds.width,
      height: bounds.height,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });

  expect(layout.width).toBeGreaterThan(layout.viewportWidth * 0.8);
  expect(layout.height).toBeGreaterThan(layout.viewportHeight * 0.7);

  const pageCanScroll = await window.getByTestId("runtime-setup-view").evaluate((node) => {
    node.scrollTop = node.scrollHeight;
    return node.scrollTop > 0;
  });
  expect(pageCanScroll).toBe(false);

  const logPanelScrollState = await window.getByTestId("runtime-details-body").evaluate((node) => {
    const overflows = node.scrollHeight > node.clientHeight + 1;
    node.style.scrollBehavior = "auto";
    node.scrollTop = node.scrollHeight;
    return { overflows, canScroll: node.scrollTop > 0 };
  });
  expect(logPanelScrollState.overflows ? logPanelScrollState.canScroll : true).toBe(true);

  const footerPinned = await window.getByTestId("runtime-card").evaluate((node) => {
    const footer = node.querySelector(".runtime-footer");
    if (!footer) return false;
    const cardBounds = node.getBoundingClientRect();
    const footerBounds = footer.getBoundingClientRect();
    return cardBounds.bottom - footerBounds.bottom < 48;
  });
  expect(footerPinned).toBe(true);

  await quitApp(app);
});

test("runtime setup view collapses cleanly on compact windows", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_RUNTIME_FIXTURE: JSON.stringify({
        phase: "core_missing",
        python: { available: true, supported: true, version: "3.14.4", path: "/opt/homebrew/bin/python3" },
        core: { installed: false, version: "", commandPath: "" },
        uiService: { running: false, healthy: false, host: "127.0.0.1", port: 4673, baseUrl: "http://127.0.0.1:4673/", token: "" },
        errors: [{ code: "CORE_MISSING", message: "Codex Account Manager core is not installed." }],
      }),
    },
  });

  const window = await app.firstWindow();
  await window.setViewportSize({ width: 820, height: 900 });
  await expect(window.getByTestId("runtime-setup-view")).toBeVisible();
  await expect(window.getByRole("button", { name: /install core/i })).toBeVisible();

  const pageFitsViewport = await window.evaluate(() => {
    const node = document.scrollingElement || document.documentElement;
    return node.scrollWidth <= node.clientWidth;
  });
  expect(pageFitsViewport).toBe(true);

  const actionButtonBox = await window.getByRole("button", { name: /install core/i }).boundingBox();
  expect(actionButtonBox?.width).toBeGreaterThan(120);

  await quitApp(app);
});

test("runtime setup view copies diagnostics when backend is unavailable", async () => {
  const app = await electron.launch({
    args: ["."],
    cwd: process.cwd(),
    env: {
      ...process.env,
      CAM_ELECTRON_DISABLE_TRAY: "1",
      CAM_ELECTRON_RUNTIME_FIXTURE: JSON.stringify({
        phase: "core_missing",
        python: { available: true, supported: true, version: "3.14.4", path: "/opt/homebrew/bin/python3" },
        core: { installed: false, version: "", commandPath: "" },
        uiService: { running: false, healthy: false, host: "127.0.0.1", port: 4673, baseUrl: "http://127.0.0.1:4673/", token: "" },
        errors: [{ code: "CORE_MISSING", message: "Codex Account Manager core is not installed." }],
      }),
    },
  });

  const window = await app.firstWindow();
  await window.getByTestId("runtime-details-toggle").click();
  await window.getByRole("button", { name: /copy logs/i }).click();
  await expect(window.getByRole("status")).toContainText("Copied");

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
  await expect(window.getByTestId("electron-renderer")).toBeVisible({ timeout: 10000 });
  const sidebar = window.getByTestId("desktop-sidebar");
  await expect(sidebar).toHaveClass(/fixed|minimal/);

  await window.getByRole("button", { name: /Collapse sidebar|Expand sidebar/ }).click();
  await expect(sidebar).toHaveClass(/minimal|fixed/);
  await window.getByRole("button", { name: /Expand sidebar/ }).click();
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
  await expect(window.getByRole("button", { name: /Auto Refresh/i })).toHaveCount(0);
  await expect(window.getByRole("button", { name: /Notifications/i })).toHaveCount(0);
  await expect(window.getByRole("button", { name: /Guide & Help/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Update/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Debug/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Usage/i })).toHaveCount(0);
  await expect(window.getByTestId("sidebar-current-profile")).toContainText("work");
  await expect(window.getByTestId("sidebar-current-profile")).toContainText("work@example.test");

  await window.getByTestId("desktop-sidebar").getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();
  await expect(window.getByText("Appearance")).toBeVisible();
  await expect(window.getByText("Maintenance")).toBeVisible();
  await expect(window.getByText("Current account refresh", { exact: true }).first()).toBeVisible();
  await expect(window.getByText("All accounts refresh", { exact: true }).first()).toBeVisible();
  await expect(window.getByText("Notifications", { exact: true }).first()).toBeVisible();

  await window.getByRole("button", { name: "Auto Switch" }).click();
  await expect(window.getByTestId("autoswitch-view")).toBeVisible();
  await expect(window.getByText("Auto-switch rules")).toBeVisible();
  await expect(window.getByText("Switch Chain Preview")).toBeVisible();

  await window.getByRole("button", { name: "Profiles" }).click();
  await expect(window.getByRole("button", { name: /Add Account/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Remove All/i })).toBeVisible();
  await expect(window.getByRole("button", { name: /Columns/i })).toBeVisible();
  await expect(window.locator("button[aria-label*='row actions' i], button[title*='row actions' i], button[data-row-actions]").first()).toBeVisible();
  await expect(window.locator("td[data-col='email']").first()).toHaveText("work@example.test");
  await expect.poll(() => window.locator(".profiles-table-wrap").evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  await window.setViewportSize({ width: 920, height: 700 });
  await expect(window.locator(".profiles-table-wrap table")).toBeVisible();
  await expect(window.locator("th[data-col='h5remain']").first()).toBeHidden();
  await expect(window.getByTestId("desktop-sidebar")).toHaveClass(/minimal/);

  await quitApp(app);
});

test("settings page keeps scrolling, footer actions, and compact ordering stable", async () => {
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
  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();

  await window.setViewportSize({ width: 980, height: 620 });
  const scrollState = await window.getByTestId("settings-view").evaluate((node) => {
    node.style.scrollBehavior = "auto";
    const overflows = node.scrollHeight > node.clientHeight + 1;
    node.scrollTop = node.scrollHeight;
    const lastCard = node.querySelector('[data-testid="settings-card-system"]');
    const viewRect = node.getBoundingClientRect();
    const lastRect = lastCard?.getBoundingClientRect();
    return {
      overflows,
      canScroll: node.scrollTop > 0,
      widthFits: node.scrollWidth <= node.clientWidth + 1,
      lastCardVisible: !!lastRect && lastRect.bottom <= viewRect.bottom + 1,
    };
  });

  expect(scrollState.overflows ? scrollState.canScroll : true).toBe(true);
  expect(scrollState.widthFits).toBe(true);
  expect(scrollState.lastCardVisible).toBe(true);

  await window.setViewportSize({ width: 820, height: 720 });
  const compactLayout = await window.getByTestId("settings-view").evaluate((node) => {
    const ids = [
      "settings-card-appearance",
      "settings-card-refresh",
      "settings-card-notifications",
      "settings-card-maintenance",
      "settings-card-system",
    ];
    const topById = Object.fromEntries(ids.map((id) => {
      const card = node.querySelector(`[data-testid="${id}"]`);
      return [id, card ? card.getBoundingClientRect().top : null];
    }));
    const footersStayInside = Array.from(node.querySelectorAll(".settings-card-footer")).every((footer) => {
      const footerRect = footer.getBoundingClientRect();
      const cardRect = footer.closest(".settings-card-shell")?.getBoundingClientRect();
      return !!cardRect
        && footerRect.left >= cardRect.left - 1
        && footerRect.right <= cardRect.right + 1
        && footerRect.bottom <= cardRect.bottom + 1;
    });
    return {
      widthFits: node.scrollWidth <= node.clientWidth + 1,
      topById,
      footersStayInside,
    };
  });

  expect(compactLayout.widthFits).toBe(true);
  expect(compactLayout.topById["settings-card-appearance"]).toBeLessThan(compactLayout.topById["settings-card-refresh"]);
  expect(compactLayout.topById["settings-card-refresh"]).toBeLessThan(compactLayout.topById["settings-card-notifications"]);
  expect(compactLayout.topById["settings-card-notifications"]).toBeLessThan(compactLayout.topById["settings-card-maintenance"]);
  expect(compactLayout.topById["settings-card-maintenance"]).toBeLessThan(compactLayout.topById["settings-card-system"]);
  expect(compactLayout.footersStayInside).toBe(true);

  await quitApp(app);
});

test("settings theme buttons apply explicit and auto theme modes", async () => {
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
  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-card-appearance")).toBeVisible();

  await window.getByTestId("settings-card-appearance").getByRole("button", { name: "Dark" }).click();
  await expect.poll(() => window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }))).toEqual({ theme: "dark", mode: "dark" });

  await window.getByTestId("settings-card-appearance").getByRole("button", { name: "Light" }).click();
  await expect.poll(() => window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }))).toEqual({ theme: "light", mode: "light" });

  await window.getByTestId("settings-card-appearance").getByRole("button", { name: "Auto" }).click();
  await expect.poll(() => window.evaluate(() => document.documentElement.dataset.themeMode)).toBe("auto");
  const autoTheme = await window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }));
  expect(["dark", "light"]).toContain(autoTheme.theme);
  expect(autoTheme.mode).toBe("auto");

  await quitApp(app);
});

test("auto switch controls stay within the selection policy card", async () => {
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
  await window.setViewportSize({ width: 1280, height: 860 });
  await window.getByRole("button", { name: "Auto Switch" }).click();
  await expect(window.getByTestId("autoswitch-view")).toBeVisible();

  const layout = await window.locator(".metric-pair-grid").first().evaluate((grid) => {
    const gridRect = grid.getBoundingClientRect();
    const rowRects = Array.from(grid.children, (child) => child.getBoundingClientRect());
    const overflowsGrid = grid.scrollWidth > grid.clientWidth + 1;
    const rowBleeds = rowRects.some((rect) => rect.left < gridRect.left - 1 || rect.right > gridRect.right + 1);
    return { overflowsGrid, rowBleeds };
  });

  expect(layout.overflowsGrid).toBe(false);
  expect(layout.rowBleeds).toBe(false);

  await quitApp(app);
});

test("desktop views use space-first layout without accidental page scrolling", async () => {
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
  await expect(window.getByTestId("electron-renderer")).toBeVisible({ timeout: 10000 });

  const viewByLabel = [
    { label: "Profiles", selector: ".profiles-view", allowShortViewOverflow: false },
    { label: "Auto Switch", selector: ".autoswitch-view", allowShortViewOverflow: false },
    { label: "Settings", selector: ".settings-view", allowShortViewOverflow: true, allowViewScroller: true },
    { label: "Guide & Help", selector: ".guide-view", allowShortViewOverflow: false },
    { label: "Update", selector: ".update-view", allowShortViewOverflow: false },
    { label: "Debug", selector: ".debug-view", allowShortViewOverflow: false },
    { label: "About", selector: ".about-view", allowShortViewOverflow: false },
  ];

  async function measureView(selector) {
    return window.locator(selector).evaluate((view) => {
      const workspace = document.querySelector(".workspace");
      const viewRect = view.getBoundingClientRect();
      const measuredChildren = Array.from(view.querySelectorAll(".section-card,.settings-card,.auto-switch-card,.table-wrap,.debug-log-panel"))
        .map((node) => node.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0);
      const lastBottom = measuredChildren.length
        ? Math.max(...measuredChildren.map((rect) => rect.bottom))
        : viewRect.bottom;
      const activeScrollers = Array.from(view.querySelectorAll(".scrollable"))
        .filter((node) => /(auto|scroll)/.test(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight + 1)
        .map((node) => node.className);
      return {
        documentScrolls: document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight + 1,
        workspaceScrolls: workspace ? workspace.scrollHeight > workspace.clientHeight + 1 : false,
        viewOverflows: view.scrollHeight > view.clientHeight + 1,
        viewOverflowY: getComputedStyle(view).overflowY,
        bottomGap: Math.round(viewRect.bottom - lastBottom),
        activeScrollers,
      };
    });
  }

  for (const viewport of [
    { width: 1280, height: 800, short: false },
    { width: 1600, height: 1000, short: false },
    { width: 800, height: 600, short: true },
  ]) {
    await window.setViewportSize({ width: viewport.width, height: viewport.height });

    for (const view of viewByLabel) {
      await window.getByRole("button", { name: view.label }).click();
      await expect(window.locator(view.selector)).toBeVisible();
      const layout = await measureView(view.selector);

      expect(layout.documentScrolls, `${viewport.width}x${viewport.height} ${view.label} document scroll`).toBe(false);
      expect(layout.workspaceScrolls, `${viewport.width}x${viewport.height} ${view.label} workspace scroll`).toBe(false);

      if (view.allowViewScroller) {
        expect(layout.viewOverflowY, `${viewport.width}x${viewport.height} ${view.label} overflow mode`).toBe("auto");
      } else if (viewport.short && view.allowShortViewOverflow) {
        expect(layout.viewOverflowY, `${viewport.width}x${viewport.height} ${view.label} short overflow mode`).toBe("auto");
      } else {
        expect(layout.viewOverflows, `${viewport.width}x${viewport.height} ${view.label} view overflow`).toBe(false);
      }

      const allowedScrollTarget = view.label === "Settings"
        ? /profiles-table-wrap|debug-log-panel|release-sections|settings-view/
        : /profiles-table-wrap|debug-log-panel|release-sections/;
      expect(layout.bottomGap, `${viewport.width}x${viewport.height} ${view.label} bottom gap`).toBeLessThanOrEqual(40);
      expect(layout.activeScrollers.every((className) => allowedScrollTarget.test(String(className))), `${viewport.width}x${viewport.height} ${view.label} scroll target`).toBe(true);
    }
  }

  await quitApp(app);
});
