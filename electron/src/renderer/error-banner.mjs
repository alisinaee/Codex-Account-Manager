export function getErrorBannerCountdownSeconds(expiresAtMs, nowMs = Date.now()) {
  const expiresAt = Number(expiresAtMs);
  const now = Number(nowMs);
  if (!Number.isFinite(expiresAt) || !Number.isFinite(now)) {
    return 0;
  }
  const remainingMs = Math.max(0, expiresAt - now);
  return Math.max(0, Math.min(30, Math.ceil(remainingMs / 1000)));
}
