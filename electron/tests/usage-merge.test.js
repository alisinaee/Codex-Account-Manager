const test = require('node:test');
const assert = require('node:assert/strict');

test('mergeUsagePayload clears transient loading_usage when fresh profile usage arrives', async () => {
  const { mergeUsagePayload } = await import('../src/renderer/usage-merge.mjs');

  const prevUsage = {
    current_profile: 'work',
    profiles: [
      {
        name: 'work',
        loading_usage: true,
        error: null,
        usage_5h: { remaining_percent: null, resets_at: null, text: '-' },
        usage_weekly: { remaining_percent: null, resets_at: null, text: '-' },
      },
    ],
  };

  const nextUsage = {
    refreshed_at: new Date().toISOString(),
    current_profile: 'work',
    profiles: [
      {
        name: 'work',
        error: null,
        usage_5h: { remaining_percent: 72, resets_at: 1700000000, text: '72%' },
        usage_weekly: { remaining_percent: 81, resets_at: 1700000000, text: '81%' },
      },
    ],
  };

  const merged = mergeUsagePayload(prevUsage, nextUsage, { profiles: [{ name: 'work' }] }, { account_hint: 'work@example.test' });

  assert.equal(merged.profiles[0].loading_usage, false);
  assert.equal(merged.profiles[0].usage_5h.remaining_percent, 72);
  assert.equal(merged.profiles[0].usage_weekly.remaining_percent, 81);
});
