const test = require("node:test");
const assert = require("node:assert/strict");

test("downloadBackendExport falls back to desktop.getBackendState and clicks an attached anchor", async () => {
  const { downloadBackendExport } = await import("../src/renderer/download-utils.mjs");

  const events = [];
  const anchor = {
    href: "",
    download: "",
    click() {
      events.push(["click", this.href, this.download]);
    },
    remove() {
      events.push(["remove"]);
    },
  };
  const documentRef = {
    body: {
      appendChild(node) {
        events.push(["append", node === anchor]);
      },
    },
    createElement(tag) {
      assert.equal(tag, "a");
      return anchor;
    },
  };
  const urlApi = {
    createObjectURL(blob) {
      events.push(["createObjectURL", blob]);
      return "blob:export";
    },
    revokeObjectURL(url) {
      events.push(["revoke", url]);
    },
  };
  const desktop = {
    async getBackendState() {
      return { baseUrl: "http://127.0.0.1:4673/", token: "session-token" };
    },
  };
  const fetchImpl = async (href, options) => {
    events.push(["fetch", href, options.method]);
    return {
      ok: true,
      async blob() {
        return { size: 3, type: "application/octet-stream" };
      },
    };
  };

  const backend = await downloadBackendExport({
    desktop,
    backendState: null,
    fetchImpl,
    path: "/api/local/export/download",
    params: { id: "export-1" },
    filename: "profiles.camzip",
    documentRef,
    urlApi,
    setTimeoutImpl: (fn) => {
      fn();
      return 1;
    },
  });

  assert.deepEqual(backend, { baseUrl: "http://127.0.0.1:4673/", token: "session-token" });
  assert.deepEqual(events, [
    ["fetch", "http://127.0.0.1:4673/api/local/export/download?token=session-token&id=export-1", "GET"],
    ["createObjectURL", { size: 3, type: "application/octet-stream" }],
    ["append", true],
    ["click", "blob:export", "profiles.camzip"],
    ["remove"],
    ["revoke", "blob:export"],
  ]);
});

test("triggerBlobDownload attaches the anchor before clicking", async () => {
  const { triggerBlobDownload } = await import("../src/renderer/download-utils.mjs");

  const order = [];
  const anchor = {
    href: "",
    download: "",
    click() {
      order.push("click");
    },
    remove() {
      order.push("remove");
    },
  };
  const documentRef = {
    body: {
      appendChild(node) {
        order.push(node === anchor ? "append" : "append-other");
      },
    },
    createElement() {
      return anchor;
    },
  };
  const urlApi = {
    createObjectURL() {
      return "blob:test";
    },
    revokeObjectURL() {
      order.push("revoke");
    },
  };

  triggerBlobDownload({ size: 1 }, "debug.json", {
    documentRef,
    urlApi,
    setTimeoutImpl: (fn) => {
      fn();
      return 1;
    },
  });

  assert.deepEqual(order, ["append", "click", "remove", "revoke"]);
});
