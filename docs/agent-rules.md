# AI Agent Rules & Change Memory

## Project Snapshot
- Keep updates focused on architecture, behavior rules, and high-impact changes only.
- Prefer short, implementation-focused bullets over narrative prose.

## Behavior Rules
- Keep this file concise and clear for AI agents.
- Update this file after assistant turns that edit repo-tracked files.
- Capture new user behavior instructions as short imperative rules.
- Skip updates when there are no file edits and no new behavior instructions.
- Retain only the latest 20 change entries.
- Ensure documentation updates are thorough and written under the `docs/` folder.
- Ensure i want one command to fullllly test.
- Ensure dude its too slow similations i want to each swith happen about 30 sec also colorufll outputs , to know what happend what seelct in chain for next see the algorithm and.
- Ensure more fucus on web ui also need to user this is cross platfrom too.
- Ensure md file you need to blur my account emails first on image.
- Update the readme to include this data ( update readme.
- Ensure i dont want this scroll just on auto refresh , the loading cuase the change a little bit in columns , you need just fix that remove scroll on table.
- Ensure i want to see details of that and progress bar for instalion to find the issue.
- Ensure make codex-account electron command to show always info and progress.
- Ensure like other Mac icons it should be a rounded icon.

## Recent Changes (Last 20)
### 2026-04-27T20:29:36+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Aligned sidebar usage percentage text on the same horizontal line as the usage bar and reduced sidebar percentage typography size for a cleaner compact readout.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:e68e8f6cd4b3 -->

### 2026-04-27T20:22:10+03:30
- Changed files: `electron/src/renderer/components/SettingsCardShell.jsx`, `electron/src/renderer/SettingsView.jsx`, `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Extracted shared Settings card-shell/subsection primitives and migrated Auto Switch controls to the same settings design system and layout container, while constraining the card stack to keep the view-level no-scroll layout behavior.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:c46798e176af -->

### 2026-04-27T20:06:33+03:30
- Changed files: `electron/src/renderer/table-layout.mjs`, `electron/tests/table-layout.test.js`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Reduced the profile-name column flex weight and tightened regression bounds so profile stays compact relative to usage columns while preserving email/profile balance.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:5b6eb86ef0d4 -->

### 2026-04-27T20:02:03+03:30
- Changed files: `electron/src/renderer/table-layout.mjs`, `electron/tests/table-layout.test.js`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Reduced the profile table email column flex weight and added unit/Electron regressions so email remains wider than profile but cannot dominate the table.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:0b1028c99014 -->

### 2026-04-27T19:59:19+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Removed seconds from the profile table W remain column only, while preserving seconds in 5h remain and adding Electron E2E coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:1a396569863b -->

### 2026-04-27T19:49:17+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/table-layout.mjs`, `electron/src/styles/components.css`, `electron/tests/table-layout.test.js`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Added adaptive profile-table column width calculation from the currently visible columns, removed static colgroup width overrides, and covered the 9/16 column layout with unit and Electron E2E regressions.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:69eb752c7658 -->

### 2026-04-27T18:45:30+03:30
- Changed files: `electron/src/styles/tokens.css`, `electron/src/styles/components.css`, `electron/tests/theme.test.js`
- Summary: Defined a full theme-specific toggle palette for dark and light themes, including separate track and thumb colors for off/on states, and added regression coverage for the required toggle tokens.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:65f6172e5e99 -->

### 2026-04-27T18:34:41+03:30
- Changed files: `electron/src/styles/components.css`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Added a short-height responsive rule that turns the top-level Electron settings cards into a two-column grid when the window is not compact, and updated the settings E2E coverage to target that breakpoint behavior; Electron E2E launch is currently blocked here because the renderer opens to chrome-error://chromewebdata/.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:f2a278e2d7f1 -->

### 2026-04-27T18:14:31+03:30
- Changed files: `electron/src/styles/tokens.css`, `electron/src/styles/components.css`
- Summary: Adjusted the shared toggle off-state so light theme uses a softer slate thumb instead of the previous heavy dark circle, while keeping the darker off thumb for dark theme.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:4ad64feb60e2 -->

### 2026-04-27T18:11:18+03:30
- Changed files: `electron/src/styles/tokens.css`, `electron/src/styles/components.css`
- Summary: Adjusted the shared toggle switch so the enabled thumb uses a darker green on light theme while keeping the existing bright green track color.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:67a341995460 -->

### 2026-04-27T18:09:23+03:30
- Changed files: `electron/src/renderer/icon-pack.jsx`
- Summary: Replaced the auto theme header icon with a clearer system-following monitor-and-spark glyph while keeping the existing theme-cycle behavior and tests.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:5e2b59018bd1 -->

### 2026-04-27T18:06:01+03:30
- Changed files: `electron/src/styles/components.css`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Fixed narrow-width Electron settings card overlap by preserving the main settings stack in compact mode instead of flattening it with display: contents; added a regression that checks cards do not overlap.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:bb229141a01b -->

### 2026-04-27T18:01:23+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/icon-pack.jsx`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Made the header theme icon button swap its icon for auto, light, and dark modes so the control reflects the current theme state.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:b04e45945be9 -->

### 2026-04-27T17:55:39+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/SettingsView.jsx`, `electron/src/renderer/theme.mjs`, `electron/src/renderer/icon-pack.jsx`, `electron/src/styles/components.css`, `electron/tests/e2e/electron-shell.spec.js`, `electron/tests/theme.test.js`
- Summary: Moved theme control from Settings into a single top-header icon button after Refresh, removed the Appearance settings card, and added theme-cycle regression coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:9b72e3115b2f -->

### 2026-04-27T17:31:04+03:30
- Changed files: `electron/src/renderer/SettingsView.jsx`, `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`, `electron/tests/e2e/electron-shell.spec.js`
- Summary: Removed the Maintenance & Recovery settings card and moved the System info card from Settings into the About screen with matching Electron regression coverage.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:aa235d35119c -->

### 2026-04-27T15:13:39+03:30
- Changed files: `electron/src/renderer/SettingsView.jsx`, `electron/src/styles/components.css`
- Summary: Simplified the Electron settings internals so each settings group now uses a single stacked subsection lane instead of side-by-side inner grids, making the page follow the `Current account refresh` box pattern more consistently.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:2dbfb2d0af9c -->

### 2026-04-27T14:48:26+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/renderer/SettingsView.jsx`, `electron/src/renderer/theme.mjs`, `electron/src/styles/components.css`, `electron/src/styles/tokens.css`, `electron/tests/e2e/electron-shell.spec.js`, `electron/tests/theme.test.js`
- Summary: Extracted the Electron settings screen into a dedicated module, rebuilt it as a responsive card-based layout with bottom-right section actions, fixed settings-page scrolling, and completed renderer-side light/dark/auto theme application with new regression coverage.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:7c2a93f7f0f8 -->

### 2026-04-27T13:11:42+03:30
- Changed files: `electron/src/renderer/App.jsx`, `electron/src/styles/components.css`
- Summary: Refined the Electron Settings layout into a full-width card stack, token-driven 2-to-1 responsive inner grids, aligned right-edge controls, and stabilized shared stepper sizing and Windows helper-copy rows.
- Behavior impact: Added or refreshed 4 behavior rule(s) from user instructions.
<!-- fingerprint:4e62bad66447 -->

### 2026-04-27T09:25:57+03:30
- Changed files: `electron/src/renderer/App.jsx`, `docs/agent-rules.md`
- Summary: Disabled automatic core installation on the Electron setup screen; install steps now wait for explicit user action.
- Behavior impact: Recorded code-level deltas for future AI context.
<!-- fingerprint:69791133204e -->

### 2026-04-27T09:22:24+03:30
- Changed files: `docs/agent-rules.md`
- Summary: Recorded that Electron prerequisite install flow must work generally across Windows systems, not only the local machine.
- Behavior impact: Added or refreshed 1 behavior rule(s) from user instructions.
<!-- fingerprint:8acfc423dee7 -->

## Last Updated
- 2026-04-27T20:29:36+03:30
