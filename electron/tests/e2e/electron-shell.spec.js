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

test("profile table redistributes width when optional columns are disabled", async () => {
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
  await window.setViewportSize({ width: 1600, height: 900 });
  await expect(window.getByTestId("profiles-view")).toBeVisible();

  await window.getByRole("button", { name: /Columns/i }).click();
  for (const label of ["Status", "Plan", "Paid", "Id", "Added", "Note", "Auto"]) {
    await window.getByLabel(label, { exact: true }).uncheck();
  }
  await window.getByRole("button", { name: "Done" }).click();
  await expect(window.getByRole("button", { name: /Columns/i })).toContainText("9/16");
  await expect(window.locator("td[data-col='h5remain']").first()).toHaveText(/\d+s$/);
  await expect(window.locator("td[data-col='weeklyremain']").first()).not.toHaveText(/\d+s$/);

  for (const viewport of [
    { width: 1280, height: 860, sizeClass: "size-normal", expectedColumns: ["profile", "email", "h5", "h5remain", "weekly", "weeklyremain", "actions"] },
    { width: 1600, height: 900, sizeClass: "size-wide", expectedColumns: ["profile", "email", "h5", "h5remain", "h5reset", "weekly", "weeklyremain", "weeklyreset", "actions"] },
    { width: 2200, height: 1000, sizeClass: "size-ultrawide", expectedColumns: ["profile", "email", "h5", "h5remain", "h5reset", "weekly", "weeklyremain", "weeklyreset", "actions"] },
  ]) {
    await window.setViewportSize(viewport);
    await expect.poll(() => window.evaluate(() => document.body.className)).toContain(viewport.sizeClass);
    await expect(window.locator("th[data-col='actions']")).toBeVisible();

    const layout = await window.locator(".profiles-table-wrap").evaluate((wrap) => {
      const rectOf = (selector) => {
        const rect = wrap.querySelector(selector)?.getBoundingClientRect();
        return rect ? { left: rect.left, right: rect.right, width: rect.width } : null;
      };
      const visibleHeaderKeys = Array.from(wrap.querySelectorAll("th[data-col]"))
        .filter((node) => node.getBoundingClientRect().width > 0)
        .map((node) => node.getAttribute("data-col"));
      const actionsCell = rectOf("td[data-col='actions']");
      const actionsGroup = rectOf("td[data-col='actions'] .actions-cell");
      const emailCell = rectOf("td[data-col='email']");
      const profileCell = rectOf("td[data-col='profile']");
      const h5Cell = rectOf("td[data-col='h5']");
      const h5RemainCell = rectOf("td[data-col='h5remain']");

      return {
        scrollFits: wrap.scrollWidth <= wrap.clientWidth + 1,
        visibleHeaderKeys,
        actionsWidth: actionsCell?.width || 0,
        actionsTrailingGap: actionsCell && actionsGroup ? Math.round(actionsCell.right - actionsGroup.right) : 999,
        emailWidth: emailCell?.width || 0,
        profileWidth: profileCell?.width || 0,
        h5Width: h5Cell?.width || 0,
        h5RemainWidth: h5RemainCell?.width || 0,
      };
    });

    expect(layout.scrollFits, `${viewport.width}px table overflow`).toBe(true);
    expect(layout.visibleHeaderKeys, `${viewport.width}px visible columns`).toEqual(viewport.expectedColumns);
    expect(layout.actionsWidth, `${viewport.width}px actions width`).toBeLessThanOrEqual(120);
    expect(layout.actionsTrailingGap, `${viewport.width}px actions trailing gap`).toBeLessThanOrEqual(8);
    expect(layout.emailWidth, `${viewport.width}px email width`).toBeGreaterThan(layout.profileWidth);
    expect(layout.emailWidth, `${viewport.width}px email width balance`).toBeLessThan(layout.profileWidth * 1.6);
    expect(layout.profileWidth, `${viewport.width}px profile width balance`).toBeLessThan(layout.h5Width);
    expect(layout.profileWidth, `${viewport.width}px profile width`).toBeGreaterThan(layout.h5RemainWidth);
  }

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
  await expect(window.getByTestId("electron-renderer")).toBeVisible();
  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();

  await window.setViewportSize({ width: 980, height: 620 });
  const scrollState = await window.getByTestId("settings-view").evaluate((node) => {
    node.style.scrollBehavior = "auto";
    const overflows = node.scrollHeight > node.clientHeight + 1;
    node.scrollTop = node.scrollHeight;
    const cards = Array.from(node.querySelectorAll(".settings-card-shell"));
    const lastCard = cards.at(-1);
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

  await window.setViewportSize({ width: 620, height: 720 });
  const compactLayout = await window.getByTestId("settings-view").evaluate((node) => {
    const ids = [
      "settings-card-refresh",
      "settings-card-notifications",
    ];
    const rectById = Object.fromEntries(ids.map((id) => {
      const card = node.querySelector(`[data-testid="${id}"]`);
      if (!card) return [id, null];
      const rect = card.getBoundingClientRect();
      return [id, { top: rect.top, bottom: rect.bottom, height: rect.height }];
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
      rectById,
      footersStayInside,
    };
  });

  expect(compactLayout.widthFits).toBe(true);
  expect(compactLayout.rectById["settings-card-refresh"].top).toBeLessThan(compactLayout.rectById["settings-card-notifications"].top);
  expect(compactLayout.rectById["settings-card-refresh"].bottom).toBeLessThanOrEqual(compactLayout.rectById["settings-card-notifications"].top);
  expect(compactLayout.footersStayInside).toBe(true);

  await quitApp(app);
});

test("settings cards use two columns at short height when width is non-compact", async () => {
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
  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();

  const shortHeightLayout = await window.getByTestId("settings-view").evaluate((node) => {
    document.body.classList.remove("height-tall", "height-normal", "height-short");
    document.body.classList.add("height-short");
    const ids = [
      "settings-card-refresh",
      "settings-card-notifications",
    ];
    const rectById = Object.fromEntries(ids.map((id) => {
      const card = node.querySelector(`[data-testid="${id}"]`);
      if (!card) return [id, null];
      const rect = card.getBoundingClientRect();
      return [id, {
        top: rect.top,
        left: rect.left,
        right: rect.right,
        bottom: rect.bottom,
      }];
    }));
    return {
      bodyClassName: document.body.className,
      widthFits: node.scrollWidth <= node.clientWidth + 1,
      rectById,
    };
  });

  expect(shortHeightLayout.bodyClassName).not.toContain("size-compact");
  expect(shortHeightLayout.bodyClassName).toContain("height-short");
  expect(shortHeightLayout.widthFits).toBe(true);
  expect(Math.abs(shortHeightLayout.rectById["settings-card-refresh"].top - shortHeightLayout.rectById["settings-card-notifications"].top)).toBeLessThanOrEqual(4);
  expect(shortHeightLayout.rectById["settings-card-refresh"].right).toBeLessThan(shortHeightLayout.rectById["settings-card-notifications"].left);

  await quitApp(app);
});

test("system info lives in about and maintenance is removed from settings", async () => {
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
  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();
  await expect(window.getByText("Maintenance & Recovery")).toHaveCount(0);
  await expect(window.getByText("System info")).toHaveCount(0);

  await window.getByRole("button", { name: "About" }).click();
  await expect(window.locator(".about-view")).toBeVisible();
  await expect(window.getByText("System info")).toBeVisible();
  await expect(window.getByText("Platform")).toBeVisible();

  await quitApp(app);
});

test("header theme button cycles modes and settings no longer shows appearance controls", async () => {
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
  await expect(window.getByRole("button", { name: "Refresh" })).toBeVisible();
  const topActionOrder = await window.locator(".top-actions > *").evaluateAll((nodes) => (
    nodes.map((node) => {
      const button = node.matches("button") ? node : node.querySelector("button");
      return button?.dataset.testid || button?.getAttribute("aria-label") || button?.textContent?.trim() || "";
    })
  ));
  expect(topActionOrder).toEqual(["Restart", "Refresh", "topbar-theme-button"]);

  const themeButton = window.getByTestId("topbar-theme-button");
  await expect(themeButton).toBeVisible();
  await expect.poll(() => window.evaluate(() => document.documentElement.dataset.themeMode)).toBe("auto");
  await expect(window.getByTestId("theme-icon-auto")).toBeVisible();
  await expect(window.getByTestId("theme-icon-light")).toHaveCount(0);
  await expect(window.getByTestId("theme-icon-dark")).toHaveCount(0);

  await themeButton.click();
  await expect.poll(() => window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }))).toEqual({ theme: "light", mode: "light" });
  await expect(window.getByTestId("theme-icon-auto")).toHaveCount(0);
  await expect(window.getByTestId("theme-icon-light")).toBeVisible();
  await expect(window.getByTestId("theme-icon-dark")).toHaveCount(0);

  await themeButton.click();
  await expect.poll(() => window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }))).toEqual({ theme: "dark", mode: "dark" });
  await expect(window.getByTestId("theme-icon-auto")).toHaveCount(0);
  await expect(window.getByTestId("theme-icon-light")).toHaveCount(0);
  await expect(window.getByTestId("theme-icon-dark")).toBeVisible();

  await themeButton.click();
  await expect.poll(() => window.evaluate(() => document.documentElement.dataset.themeMode)).toBe("auto");
  const autoTheme = await window.evaluate(() => ({
    theme: document.documentElement.dataset.theme,
    mode: document.documentElement.dataset.themeMode,
  }));
  expect(["dark", "light"]).toContain(autoTheme.theme);
  expect(autoTheme.mode).toBe("auto");
  await expect(window.getByTestId("theme-icon-auto")).toBeVisible();
  await expect(window.getByTestId("theme-icon-light")).toHaveCount(0);
  await expect(window.getByTestId("theme-icon-dark")).toHaveCount(0);

  await window.getByRole("button", { name: "Settings" }).click();
  await expect(window.getByTestId("settings-view")).toBeVisible();
  await expect(window.getByTestId("settings-card-appearance")).toHaveCount(0);

  await quitApp(app);
});

test("auto switch uses parity chain layout and editor behavior", async () => {
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
  await expect(window.getByTestId("autoswitch-card-summary")).toHaveCount(0);
  await expect(window.getByTestId("autoswitch-card-chain").getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(window.locator(".chain-track .chain-arrow")).toHaveCount(1);

  const selectionLayout = await window.locator(".metric-pair-grid").first().evaluate((grid) => {
    const gridRect = grid.getBoundingClientRect();
    const rowRects = Array.from(grid.children, (child) => child.getBoundingClientRect());
    const overflowsGrid = grid.scrollWidth > grid.clientWidth + 1;
    const rowBleeds = rowRects.some((rect) => rect.left < gridRect.left - 1 || rect.right > gridRect.right + 1);
    const stacked = rowRects.length > 1 ? rowRects[1].top >= rowRects[0].bottom - 1 : true;
    return { overflowsGrid, rowBleeds, stacked };
  });

  expect(selectionLayout.overflowsGrid).toBe(false);
  expect(selectionLayout.rowBleeds).toBe(false);
  expect(selectionLayout.stacked).toBe(true);

  const chainLayout = await window.getByTestId("autoswitch-view").evaluate((view) => {
    const executionCard = view.querySelector('[data-testid="autoswitch-card-execution"]');
    const chainCard = view.querySelector('[data-testid="autoswitch-card-chain"]');
    const preview = chainCard?.querySelector(".chain-track");
    const executionRect = executionCard?.getBoundingClientRect();
    const chainRect = chainCard?.getBoundingClientRect();
    const previewStyle = preview ? getComputedStyle(preview) : null;
    return {
      hasChainFooter: !!chainCard?.querySelector(".settings-card-footer"),
      fullWidthAligned: !!executionRect && !!chainRect
        && Math.abs(executionRect.left - chainRect.left) <= 2
        && Math.abs(executionRect.right - chainRect.right) <= 2,
      previewWraps: previewStyle?.flexWrap === "wrap",
      previewFitsWidth: preview ? preview.scrollWidth <= preview.clientWidth + 1 : false,
    };
  });

  expect(chainLayout.hasChainFooter).toBe(false);
  expect(chainLayout.fullWidthAligned).toBe(true);
  expect(chainLayout.previewWraps).toBe(true);
  expect(chainLayout.previewFitsWidth).toBe(true);

  await window.getByTestId("autoswitch-card-chain").getByRole("button", { name: "Edit" }).click();
  await expect(window.getByRole("heading", { name: "Edit switch chain" })).toBeVisible();
  await expect(window.locator(".chain-edit-list .chain-edit-item.locked")).toHaveCount(1);
  await expect(window.locator(".chain-edit-list .chain-edit-metric").first()).toContainText(/5H|W/);
  await expect(window.locator(".chain-edit-list .chain-edit-arrow")).toHaveCount(1);

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
