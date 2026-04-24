"use strict";

module.exports = {
  testDir: "./tests/e2e",
  timeout: 30000,
  use: {
    trace: "on-first-retry",
  },
};
