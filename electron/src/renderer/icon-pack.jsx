import React from "react";

function IconBase({ children, ...props }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
}

export function PanelLeftCloseIcon() {
  return (
    <IconBase>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
      <path d="M9 4.5v15" />
      <path d="m17.5 12-3-2.5" />
      <path d="m17.5 12-3 2.5" />
    </IconBase>
  );
}

export function PanelLeftOpenIcon() {
  return (
    <IconBase>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
      <path d="M9 4.5v15" />
      <path d="m14.5 12 3-2.5" />
      <path d="m14.5 12 3 2.5" />
    </IconBase>
  );
}

export function ProfilesIcon() {
  return (
    <IconBase>
      <circle cx="9" cy="9" r="3" />
      <path d="M4.5 18a4.5 4.5 0 0 1 9 0" />
      <circle cx="17" cy="10" r="2.5" />
      <path d="M14.5 18a3.5 3.5 0 0 1 5 0" />
    </IconBase>
  );
}

export function AutoRefreshIcon() {
  return (
    <IconBase>
      <path d="M20 5v5h-5" />
      <path d="M4 19v-5h5" />
      <path d="M6.8 9A7 7 0 0 1 18 7" />
      <path d="M17.2 15A7 7 0 0 1 6 17" />
    </IconBase>
  );
}

export function AutoSwitchIcon() {
  return (
    <IconBase>
      <path d="M7 7h13" />
      <path d="m16 4 4 3-4 3" />
      <path d="M17 17H4" />
      <path d="m8 14-4 3 4 3" />
    </IconBase>
  );
}

export function ArrowRightIcon(props) {
  return (
    <IconBase {...props}>
      <path d="M5 12h14" />
      <path d="m13 7 5 5-5 5" />
    </IconBase>
  );
}

export function DialogCloseIcon(props) {
  return (
    <IconBase {...props}>
      <path d="m7 7 10 10" />
      <path d="m17 7-10 10" />
    </IconBase>
  );
}

export function NotificationsIcon() {
  return (
    <IconBase>
      <path d="M9.5 20a2.5 2.5 0 0 0 5 0" />
      <path d="M6 8.5a6 6 0 1 1 12 0c0 3 1 4.5 2 5.5H4c1-1 2-2.5 2-5.5" />
    </IconBase>
  );
}

export function SettingsIcon() {
  return (
    <IconBase>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-4 0v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1 0-4h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 0 1 4 0v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 0 1 0 4h-.2a1 1 0 0 0-.9.6Z" />
    </IconBase>
  );
}

export function GuideIcon() {
  return (
    <IconBase>
      <path d="M6 4.5h11a1.5 1.5 0 0 1 1.5 1.5v12.5H8a3 3 0 0 0-3 3V6a1.5 1.5 0 0 1 1-1.5Z" />
      <path d="M8 8h7" />
      <path d="M8 12h7" />
      <path d="M8 16h4.5" />
    </IconBase>
  );
}

export function UpdateIcon() {
  return (
    <IconBase>
      <path d="M12 4v10" />
      <path d="m8.5 10.5 3.5 3.5 3.5-3.5" />
      <path d="M5 19h14" />
    </IconBase>
  );
}

export function DebugIcon() {
  return (
    <IconBase>
      <rect x="5" y="7" width="14" height="11" rx="2" />
      <path d="M9 4h6" />
      <path d="M10 11h4" />
      <path d="M9 14h6" />
    </IconBase>
  );
}

export function AboutIcon() {
  return (
    <IconBase>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 10v6" />
      <path d="M12 7.5h.01" />
    </IconBase>
  );
}

export function ThemeAutoIcon(props) {
  return (
    <IconBase {...props}>
      <rect x="4" y="5" width="16" height="10" rx="2.25" />
      <path d="M10 19h4" />
      <path d="M12 15v4" />
      <path d="m8 7.75.55 1.4 1.45.6-1.45.55L8 11.75l-.55-1.45L6 9.75l1.45-.6L8 7.75Z" />
    </IconBase>
  );
}

export function ThemeLightIcon(props) {
  return (
    <IconBase {...props}>
      <circle cx="12" cy="12" r="4.25" />
      <path d="M12 2.75v2.5" />
      <path d="M12 18.75v2.5" />
      <path d="m18.54 5.46-1.77 1.77" />
      <path d="m7.23 16.77-1.77 1.77" />
      <path d="M21.25 12h-2.5" />
      <path d="M5.25 12h-2.5" />
      <path d="m18.54 18.54-1.77-1.77" />
      <path d="M7.23 7.23 5.46 5.46" />
    </IconBase>
  );
}

export function ThemeDarkIcon(props) {
  return (
    <IconBase {...props}>
      <path d="M14.5 3.75a7.75 7.75 0 1 0 5.75 13.25A8.5 8.5 0 0 1 14.5 3.75Z" />
    </IconBase>
  );
}

export function DoorClosedIcon() {
  return (
    <IconBase>
      <path d="M7 4.5h8a1.5 1.5 0 0 1 1.5 1.5v12.5h-11V6A1.5 1.5 0 0 1 7 4.5Z" />
      <path d="M10.5 12h.01" />
      <path d="M3.5 19.5h17" />
    </IconBase>
  );
}
