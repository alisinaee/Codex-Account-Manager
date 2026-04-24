# Native OS Notifications Design

Date: 2026-04-24
Project: Codex Account Manager
Status: Draft approved in chat, pending final user review of written spec

## Goal

Add a new web-panel section titled `Notification (native os system)` next to the existing `Profiles` section. The section will contain a `Test` button that triggers a real native OS notification using the current profile's live usage data.

This feature must use backend-driven OS notifications, not browser notifications.

## Scope

In scope for the first implementation:

- Add a new notification card in the web panel layout beside `Profiles`
- Add a `Test` button that calls a backend API
- Build notification content from the current active profile usage
- Implement macOS native notification delivery
- Return clear backend errors on unsupported platforms
- Open the local Codex Account Manager UI URL when the macOS notification is clicked
- Use the project icon in the macOS notification where supported by the notifier backend

Out of scope for the first implementation:

- Replacing the existing browser-notification warning flow
- Linux native notification implementation
- Windows native notification implementation
- Background automatic native notifications for usage warnings
- Advanced notification actions beyond click-to-open

## Current Context

The project is a Python CLI plus local web UI, not an Electron or Tauri desktop app. The web UI is generated from `codex_account_manager/cli.py` and already contains a `Profiles` section plus notification-related browser logic.

Native notification feasibility has already been validated on macOS:

- `osascript` successfully dispatched a Notification Center notification
- `terminal-notifier` is available via Homebrew and supports:
  - opening a URL on click
  - custom app icon image
  - title, subtitle, message, grouping, and sound

This makes macOS a practical first backend without requiring a heavy desktop runtime.

## Recommended Approach

Implement a backend-native notification service behind a dedicated web API endpoint.

The UI remains thin:

- render the new section
- invoke the API on `Test`
- show success or error using existing feedback patterns

The backend owns all OS-specific behavior:

- collecting current usage data
- locating the current profile
- formatting notification text
- selecting the OS-specific notification backend
- constructing click-open URL behavior
- reporting unsupported-OS errors

This keeps platform logic out of the frontend and fits the current Python-first architecture.

## UI Design

## Layout

Add a new section in the same row as `Profiles`, producing two side-by-side cards on wider layouts.

The new card title must be:

`Notification (native os system)`

The card should contain:

- a short description that this sends a real OS notification using current profile usage
- a `Test` button

On smaller screens, it may stack using the existing responsive layout behavior.

## Interaction

When the user clicks `Test`:

1. The UI sends `POST /api/notifications/native-test`
2. The backend attempts to send a native OS notification
3. The UI reflects the result:
   - success message on success
   - existing error reporting path on failure

The UI must not attempt any OS-specific behavior directly.

## Backend Design

## API

Add a new endpoint:

- `POST /api/notifications/native-test`

Response behavior:

- `200` on successful notification dispatch
- `4xx` or `5xx` style JSON error payload for unsupported OS, missing notifier backend, missing current profile, or dispatch failure

The JSON response should be concise and structured enough for the UI to display a useful message.

## Notification Service

Add a small Python service or helper layer for native notifications rather than embedding the full logic directly inside the HTTP handler.

Responsibilities:

- determine the current platform
- build a notification payload from app state
- dispatch to the correct OS backend
- normalize errors

Suggested interface shape:

- `send_native_test_notification(base_url: str) -> dict`

The exact function name may change, but the boundary should remain small and testable.

## Data Flow

The native test action should:

1. Load the same usage data source used by the UI
2. Find the current profile
3. Extract minimal usage summary fields
4. Build the notification payload
5. Dispatch through the active OS backend

Required content for the first implementation:

- title: `Codex Account Manager`
- subtitle: `Profile <name>`
- message body: minimal current-profile usage summary

Example body:

`5H 49% left • Weekly 88% left`

If the current profile cannot be determined, return a clear error instead of sending incomplete content.

## macOS Backend

Use `terminal-notifier` as the first macOS backend.

Reasoning:

- already validated locally
- supports click-open URL behavior
- supports custom icon image
- avoids a heavier native bridge for the first version

Dispatch shape:

- title: `Codex Account Manager`
- subtitle: `Profile <name>`
- message: usage summary
- open: local UI URL such as `http://127.0.0.1:<port>/`
- icon: project asset rendered to a supported image format if needed

The click target should open the local Codex Account Manager UI in the browser.

If `terminal-notifier` is not installed on macOS, return a clear actionable error instead of silently falling back to browser notifications.

## Linux and Windows Behavior

For the first implementation:

- Linux returns `not implemented yet on this OS`
- Windows returns `not implemented yet on this OS`

The UI section still appears on those platforms so the user can exercise the feature later, but the backend response remains explicit until each platform is implemented.

## Icon Handling

The notification should use the project icon where the macOS backend supports it.

Because `terminal-notifier` expects a URL or image resource, the implementation may need to convert the existing SVG asset into a PNG or use another compatible local image path. This conversion should be deterministic and isolated to the backend helper.

If the icon cannot be attached, the notification may still be sent, but the failure should be logged and not break the main dispatch unless the backend rejects the request entirely.

## Error Handling

Explicitly handle these cases:

- unsupported OS
- notifier executable missing
- current profile missing
- current profile usage missing or malformed
- icon preparation failure
- subprocess dispatch failure

Errors must be human-readable because they surface to the web panel.

## Testing Strategy

Add focused backend tests around the new native notification path.

Required test cases:

- current profile found on macOS:
  - expected title, subtitle, message, URL, and icon path are passed to the dispatcher
- no current profile:
  - returns clear error
- unsupported platform:
  - returns clear error
- macOS notifier missing:
  - returns clear error

Use mocks for:

- platform detection
- subprocess execution
- icon conversion helper
- usage-loading helper

Do not make tests depend on a real macOS notification environment.

## Acceptance Criteria

- The web panel shows a new `Notification (native os system)` card beside `Profiles` on desktop layouts
- The card contains a `Test` button
- Clicking `Test` sends a backend request
- On macOS with `terminal-notifier` available, a real native notification appears
- The macOS notification shows:
  - app title
  - current profile name
  - minimal current-profile usage
- Clicking the macOS notification opens the Codex Account Manager UI URL
- Unsupported platforms return a clear error message through the UI
- Backend behavior is covered by automated tests

## Risks and Tradeoffs

- `terminal-notifier` adds a macOS tool dependency outside Python packaging
- icon rendering from SVG may need a small compatibility shim
- the current monolithic UI/server file increases integration risk if the new endpoint is not kept narrowly scoped

These tradeoffs are acceptable for the first release because they validate the real user-facing behavior without introducing a full desktop runtime.

## Implementation Notes

- Keep the first version narrow: test button only
- Do not refactor existing browser-notification features as part of this change
- Prefer a small helper/service boundary to reduce future Linux and Windows implementation cost
- Reuse existing usage and config helpers instead of duplicating state gathering logic
