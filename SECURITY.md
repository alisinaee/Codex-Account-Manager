# Security Policy

## Local-First Privacy Model

Codex Account Manager is designed for local account management on your machine.

- Saved profile snapshots and related metadata are stored locally under your Codex home and the local paths documented in [docs/config-and-storage.md](docs/config-and-storage.md).
- The web panel serves from your machine and binds to `127.0.0.1` by default.
- Import/export archives are generated locally and are only moved elsewhere if you explicitly copy or share them.

## What This Tool Stores

- Saved Codex auth/profile snapshots needed for switching and recovery.
- Local metadata such as profile names, timestamps, account hints, UI/service settings, and related diagnostics.
- Optional local export archives that you generate through the migration workflow.

## What This Tool Does Not Add

- No hosted backend for storing your accounts.
- No cloud sync service for your auth snapshots.
- No remote telemetry pipeline introduced by this project for profile storage or local UI usage data.

Note: the app may call upstream endpoints that Codex itself relies on for login, usage, or related account operations. This project does not replace those upstream services.

## Reporting a Vulnerability

If you find a security issue, please open a private report if possible before filing a public issue.

- Preferred: GitHub Security Advisories / private vulnerability reporting for this repository
- Fallback: open a GitHub issue only for non-sensitive security hardening topics

When reporting, include:

- affected version
- operating system
- reproduction steps
- potential impact
- whether the issue exposes local auth material, account metadata, or service access
