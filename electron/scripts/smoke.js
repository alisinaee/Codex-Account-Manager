"use strict";

const { spawn } = require("node:child_process");

const electronBinary = require("electron");

const child = spawn(electronBinary, ["."], {
  cwd: process.cwd(),
  env: {
    ...process.env,
    CAM_ELECTRON_SKIP_BACKEND: "1",
    CAM_ELECTRON_DISABLE_TRAY: "1",
  },
  stdio: "inherit",
});

let finished = false;

function end(code) {
  if (finished) return;
  finished = true;
  process.exit(code);
}

child.once("error", (error) => {
  console.error(`smoke launch failed: ${error.message}`);
  end(1);
});

child.once("exit", (code) => {
  if (!finished) {
    end(code || 1);
  }
});

setTimeout(() => {
  if (finished) return;
  child.kill("SIGTERM");
  end(0);
}, 5000);
