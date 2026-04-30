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

test('mergeUsagePayload preserves previous good rows when refresh returns only transient row errors', async () => {
  const { mergeUsagePayload } = await import('../src/renderer/usage-merge.mjs');

  const prevUsage = {
    current_profile: 'acc7',
    profiles: [
      {
        name: 'acc7',
        email: 'acc7@example.test',
        plan_type: 'team',
        is_paid: true,
        error: null,
        usage_5h: { remaining_percent: 100, resets_at: 1700000100, text: '100%' },
        usage_weekly: { remaining_percent: 88, resets_at: 1700000200, text: '88%' },
      },
      {
        name: 'acc8',
        email: 'acc8@example.test',
        plan_type: 'free',
        is_paid: false,
        error: null,
        usage_5h: { remaining_percent: 64, resets_at: 1700000300, text: '64%' },
        usage_weekly: { remaining_percent: 72, resets_at: 1700000400, text: '72%' },
      },
    ],
  };

  const nextUsage = {
    refreshed_at: new Date().toISOString(),
    current_profile: 'acc7',
    profiles: [
      {
        name: 'acc7',
        email: 'acc7@example.test',
        plan_type: null,
        is_paid: null,
        error: 'request failed: transient reset',
        usage_5h: { remaining_percent: null, resets_at: null, text: '-' },
        usage_weekly: { remaining_percent: null, resets_at: null, text: '-' },
      },
      {
        name: 'acc8',
        email: 'acc8@example.test',
        plan_type: null,
        is_paid: null,
        error: 'request failed: transient reset',
        usage_5h: { remaining_percent: null, resets_at: null, text: '-' },
        usage_weekly: { remaining_percent: null, resets_at: null, text: '-' },
      },
    ],
  };

  const merged = mergeUsagePayload(
    prevUsage,
    nextUsage,
    { profiles: [{ name: 'acc7' }, { name: 'acc8' }] },
    { account_hint: 'acc7@example.test' },
  );

  assert.equal(merged.profiles[0].usage_5h.remaining_percent, 100);
  assert.equal(merged.profiles[0].usage_weekly.remaining_percent, 88);
  assert.equal(merged.profiles[0].plan_type, 'team');
  assert.equal(merged.profiles[0].error, null);
  assert.equal(merged.profiles[1].usage_5h.remaining_percent, 64);
  assert.equal(merged.profiles[1].usage_weekly.remaining_percent, 72);
  assert.equal(merged.profiles[1].plan_type, 'free');
  assert.equal(merged.profiles[1].is_paid, false);
  assert.equal(merged.profiles[1].error, null);
});
