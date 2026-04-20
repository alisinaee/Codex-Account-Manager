from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True)
class DiagnosticsLogger:
    write_fn: Callable[[str, str, Any, bool], None]
    tail_fn: Callable[[int], list[dict]]

    def log(self, level: str, message: str, details: Any = None, echo: bool = False) -> None:
        self.write_fn(level, message, details, echo)

    def tail(self, max_lines: int = 300) -> list[dict]:
        return self.tail_fn(max_lines)


@dataclass(slots=True)
class UiConfigService:
    load_fn: Callable[[], dict]
    save_fn: Callable[[dict], dict]
    update_fn: Callable[[dict, int | None], dict]

    def load(self) -> dict:
        return self.load_fn()

    def save(self, cfg: dict) -> dict:
        return self.save_fn(cfg)

    def patch(self, patch: dict, base_revision: int | None = None) -> dict:
        return self.update_fn(patch, base_revision)


@dataclass(slots=True)
class UsageService:
    collect_fn: Callable[[int, dict | None], dict]

    def collect(self, timeout_sec: int, config: dict | None = None) -> dict:
        return self.collect_fn(timeout_sec, config)


@dataclass(slots=True)
class ProfileService:
    profiles_dir: Path

    def exists(self, name: str) -> bool:
        return (self.profiles_dir / name).is_dir()
