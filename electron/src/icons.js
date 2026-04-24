"use strict";

const path = require("node:path");

const APP_ID = "com.codexaccountmanager.desktop";
const APP_NAME = "Codex Account Manager";
const ROOT_DIR = path.resolve(__dirname, "..");
const REPO_DIR = path.resolve(ROOT_DIR, "..");

function getProjectSourceIconPath() {
  return path.join(REPO_DIR, "codex_account_manager", "assets", "codex_account_manager.svg");
}

function getElectronAssetPath(name) {
  return path.join(ROOT_DIR, "assets", name);
}

function getIconPath() {
  return getElectronAssetPath("codex-account-manager.png");
}

function getMacIconPath() {
  return getElectronAssetPath("codex-account-manager.icns");
}

function getDockIconPath() {
  return getMacIconPath();
}

function getTrayIconPath() {
  return getElectronAssetPath("codex-account-manager-tray.svg");
}

module.exports = {
  APP_ID,
  APP_NAME,
  getElectronAssetPath,
  getIconPath,
  getDockIconPath,
  getMacIconPath,
  getProjectSourceIconPath,
  getTrayIconPath,
};
