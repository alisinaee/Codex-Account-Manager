const test = require("node:test");
const assert = require("node:assert/strict");

const {
  downloadBackendExportArchive,
} = require("../src/export-download");

test("downloadBackendExportArchive fetches archive bytes and writes the chosen file", async () => {
  const calls = [];
  const result = await downloadBackendExportArchive({
    backendState: { baseUrl: "http://127.0.0.1:4673/", token: "session-token" },
    exportId: "export-1",
    filename: "profiles.camzip",
    fetchImpl: async (href, options) => {
      calls.push(["fetch", href, options.method]);
      return {
        ok: true,
        async arrayBuffer() {
          return Uint8Array.from([1, 2, 3, 4]).buffer;
        },
      };
    },
    dialogImpl: {
      async showSaveDialog(_windowRef, options) {
        calls.push(["dialog", options.defaultPath, options.filters]);
        return { canceled: false, filePath: "/tmp/profiles.camzip" };
      },
    },
    fsImpl: {
      writeFileSync(filePath, buffer) {
        calls.push(["write", filePath, Array.from(buffer)]);
      },
    },
  });

  assert.deepEqual(result, { saved: true, canceled: false, filePath: "/tmp/profiles.camzip" });
  assert.deepEqual(calls, [
    ["fetch", "http://127.0.0.1:4673/api/local/export/download?token=session-token&id=export-1", "GET"],
    ["dialog", "profiles.camzip", [{ name: "Codex Account Manager Export", extensions: ["camzip"] }]],
    ["write", "/tmp/profiles.camzip", [1, 2, 3, 4]],
  ]);
});

test("downloadBackendExportArchive returns canceled when the save dialog is dismissed", async () => {
  let wrote = false;
  const result = await downloadBackendExportArchive({
    backendState: { baseUrl: "http://127.0.0.1:4673/", token: "session-token" },
    exportId: "export-1",
    filename: "profiles.camzip",
    fetchImpl: async () => ({
      ok: true,
      async arrayBuffer() {
        return Uint8Array.from([1]).buffer;
      },
    }),
    dialogImpl: {
      async showSaveDialog() {
        return { canceled: true, filePath: "" };
      },
    },
    fsImpl: {
      writeFileSync() {
        wrote = true;
      },
    },
  });

  assert.deepEqual(result, { saved: false, canceled: true, filePath: "" });
  assert.equal(wrote, false);
});
