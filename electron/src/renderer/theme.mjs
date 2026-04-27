const VALID_THEME_MODES = new Set(["auto", "light", "dark"]);
const THEME_MODE_ORDER = ["auto", "light", "dark"];

export function normalizeThemeMode(themeMode) {
  const normalized = String(themeMode || "auto").trim().toLowerCase();
  return VALID_THEME_MODES.has(normalized) ? normalized : "auto";
}

export function resolveThemeMode(themeMode, systemTheme = "dark") {
  const normalized = normalizeThemeMode(themeMode);
  if (normalized === "auto") {
    return systemTheme === "light" ? "light" : "dark";
  }
  return normalized;
}

export function getNextThemeMode(themeMode) {
  const normalized = normalizeThemeMode(themeMode);
  const currentIndex = THEME_MODE_ORDER.indexOf(normalized);
  return THEME_MODE_ORDER[(currentIndex + 1) % THEME_MODE_ORDER.length];
}

export function resolveSystemTheme(mediaQueryList) {
  if (!mediaQueryList) {
    return "dark";
  }
  return mediaQueryList.matches ? "dark" : "light";
}

function applyThemeAttributes(target, resolvedTheme, themeMode) {
  if (!target) return;

  const nextResolvedTheme = resolveThemeMode(themeMode, resolvedTheme);
  const nextThemeMode = normalizeThemeMode(themeMode);

  if (target.dataset) {
    target.dataset.theme = nextResolvedTheme;
    target.dataset.themeMode = nextThemeMode;
  }

  if (target.style) {
    target.style.colorScheme = nextResolvedTheme;
  }
}

export function watchThemePreference(
  target,
  themeMode,
  matchMediaFn = typeof globalThis?.matchMedia === "function" ? globalThis.matchMedia.bind(globalThis) : null,
) {
  const normalizedThemeMode = normalizeThemeMode(themeMode);
  const mediaQueryList = normalizedThemeMode === "auto" && typeof matchMediaFn === "function"
    ? matchMediaFn("(prefers-color-scheme: dark)")
    : null;

  const apply = () => {
    const systemTheme = resolveSystemTheme(mediaQueryList);
    applyThemeAttributes(target, systemTheme, normalizedThemeMode);
  };

  apply();

  if (!mediaQueryList) {
    return () => {};
  }

  const handleChange = () => apply();

  if (typeof mediaQueryList.addEventListener === "function") {
    mediaQueryList.addEventListener("change", handleChange);
    return () => mediaQueryList.removeEventListener("change", handleChange);
  }

  if (typeof mediaQueryList.addListener === "function") {
    mediaQueryList.addListener(handleChange);
    return () => mediaQueryList.removeListener(handleChange);
  }

  return () => {};
}
