from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AutoSwitchState:
    active: bool
    pending_switch_due_at: float | None
    cooldown_until: float | None
    last_switch_at: float | None
    events_count: int
    config_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
