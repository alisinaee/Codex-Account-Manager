#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import sys
import time
from dataclasses import dataclass

from . import cli


@dataclass
class ProfileSim:
    name: str
    rem5: float
    remw: float
    drain5: float
    drainw: float
    eligible: bool = True
    same_principal: bool = False


class Palette:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def _use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def _c(enabled: bool, text: str, color: str) -> str:
    if not enabled:
        return text
    return f"{color}{text}{Palette.RESET}"


def _pct_color(enabled: bool, value: float | None) -> str:
    if value is None:
        return _c(enabled, "-", Palette.DIM)
    txt = f"{value:6.2f}%"
    if value < 25:
        return _c(enabled, txt, Palette.RED)
    if value < 50:
        return _c(enabled, txt, Palette.YELLOW)
    return _c(enabled, txt, Palette.GREEN)


def _fmt_bool(v: bool) -> str:
    return "yes" if v else "no"


def _build_cfg(threshold_5h: int, threshold_weekly: int, ranking_mode: str, trigger_mode: str) -> dict:
    cfg = copy.deepcopy(cli.DEFAULT_CAM_CONFIG)
    auto = cfg.setdefault("auto_switch", {})
    auto["enabled"] = True
    auto["trigger_mode"] = trigger_mode
    auto["ranking_mode"] = ranking_mode
    auto["delay_sec"] = 0
    auto["cooldown_sec"] = 0
    thr = auto.setdefault("thresholds", {})
    thr["h5_switch_pct"] = int(max(0, min(100, threshold_5h)))
    thr["weekly_switch_pct"] = int(max(0, min(100, threshold_weekly)))
    return cfg


def _usage_payload(profiles: list[ProfileSim], current_name: str) -> dict:
    rows: list[dict] = []
    for p in profiles:
        rows.append(
            {
                "name": p.name,
                "is_current": p.name == current_name,
                "auto_switch_eligible": bool(p.eligible),
                "same_principal": bool(p.same_principal),
                "usage_5h": {"remaining_percent": round(max(0.0, min(100.0, p.rem5)), 2), "resets_at": None},
                "usage_weekly": {"remaining_percent": round(max(0.0, min(100.0, p.remw)), 2), "resets_at": None},
            }
        )
    return {"current_profile": current_name, "profiles": rows}


def _find_profile(profiles: list[ProfileSim], name: str) -> ProfileSim | None:
    for p in profiles:
        if p.name == name:
            return p
    return None


def _chain_names(payload: dict, cfg: dict) -> list[str]:
    items = cli._auto_switch_chain(payload, cfg)
    return [str(x.get("name")) for x in items if x.get("name")]


def _score_rows(payload: dict, cfg: dict) -> list[tuple[float, str, float | None, float | None]]:
    rows = payload.get("profiles") or []
    current = payload.get("current_profile")
    out: list[tuple[float, str, float | None, float | None]] = []
    for r in rows:
        name = str(r.get("name") or "")
        if not name or name == current:
            continue
        if not bool(r.get("auto_switch_eligible")):
            continue
        score, _ = cli._candidate_score(r, cfg)
        p5 = cli._remaining_pct(r, "usage_5h")
        pw = cli._remaining_pct(r, "usage_weekly")
        out.append((float(score), name, p5, pw))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _candidate_exclusion_rows(payload: dict, cfg: dict) -> list[tuple[str, str]]:
    rows = payload.get("profiles") or []
    current = str(payload.get("current_profile") or "")
    auto = cfg.get("auto_switch") or {}
    same_policy = auto.get("same_principal_policy", "skip")
    out: list[tuple[str, str]] = []
    for r in rows:
        name = str(r.get("name") or "")
        if not name or name == current:
            continue
        if not bool(r.get("auto_switch_eligible")):
            out.append((name, "not eligible"))
            continue
        if same_policy == "skip" and bool(r.get("same_principal")):
            out.append((name, "same principal blocked"))
            continue
        p5 = cli._remaining_pct(r, "usage_5h")
        pw = cli._remaining_pct(r, "usage_weekly")
        if p5 is None and pw is None:
            out.append((name, "missing usage metrics"))
            continue
    return out


def _print_decision_block(use_color: bool, payload: dict, cfg: dict, prefix: str = "") -> tuple[bool, dict, str | None]:
    current = str(payload.get("current_profile") or "")
    rows = payload.get("profiles") or []
    current_row = next((r for r in rows if r.get("name") == current), None)
    if not current_row:
        print(f"{prefix}error: no current profile")
        return False, {}, None

    breached, detail = cli._trigger_breached(current_row, cfg)
    cand = cli._choose_auto_switch_candidate(payload, cfg)
    cand_name = str(cand.get("name")) if isinstance(cand, dict) and cand.get("name") else None
    p5 = cli._remaining_pct(current_row, "usage_5h")
    pw = cli._remaining_pct(current_row, "usage_weekly")

    breach_text = _c(use_color, _fmt_bool(breached), Palette.RED if breached else Palette.GREEN)
    print(
        f"{prefix}current={_c(use_color, current, Palette.CYAN)} "
        f"5h={_pct_color(use_color, p5)} weekly={_pct_color(use_color, pw)} "
        f"breached={breach_text} h5_hit={_fmt_bool(bool(detail.get('h5_hit')))} w_hit={_fmt_bool(bool(detail.get('weekly_hit')))}"
    )

    chain = _chain_names(payload, cfg)
    chain_txt = " -> ".join(chain) if chain else "-"
    print(f"{prefix}chain: {chain_txt}")

    score_rows = _score_rows(payload, cfg)
    if score_rows:
        print(f"{prefix}candidate ranking:")
        for i, (score, name, rp5, rpw) in enumerate(score_rows, start=1):
            mark = "*" if cand_name and name == cand_name else " "
            print(
                f"{prefix}  {mark}#{i} {name:<12} score={score:7.3f} "
                f"5h={_pct_color(use_color, rp5)} weekly={_pct_color(use_color, rpw)}"
            )
    else:
        print(f"{prefix}candidate ranking: -")
        excluded = _candidate_exclusion_rows(payload, cfg)
        if excluded:
            print(f"{prefix}candidate exclusions:")
            for name, reason in excluded:
                print(f"{prefix}  - {name:<12} {reason}")
    return breached, detail, cand_name


def run_simulation(args: argparse.Namespace) -> int:
    use_color = _use_color(args.color)
    cfg = _build_cfg(args.threshold_5h, args.threshold_weekly, args.ranking_mode, args.trigger_mode)
    profiles = [
        ProfileSim("alpha", rem5=args.alpha_5h, remw=args.alpha_weekly, drain5=args.alpha_drain_5h, drainw=args.alpha_drain_weekly),
        ProfileSim("beta", rem5=args.beta_5h, remw=args.beta_weekly, drain5=args.beta_drain_5h, drainw=args.beta_drain_weekly),
        ProfileSim("gamma", rem5=args.gamma_5h, remw=args.gamma_weekly, drain5=args.gamma_drain_5h, drainw=args.gamma_drain_weekly),
    ]
    current_name = args.start
    if _find_profile(profiles, current_name) is None:
        print(f"error: start profile '{current_name}' not found")
        return 2

    pending_due_tick: int | None = None
    last_switch_tick: int | None = None
    total_switches = 0

    print(_c(use_color, "Auto-Switch Simulator (Logic Mode)", Palette.BOLD))
    print(
        f"thresholds: 5h<={args.threshold_5h}% weekly<={args.threshold_weekly}% | "
        f"trigger={args.trigger_mode} ranking={args.ranking_mode} | delay={args.delay_ticks} tick(s) cooldown={args.cooldown_ticks} tick(s)"
    )
    print(f"ticks={args.ticks} sleep={args.sleep_sec:.2f}s | start={current_name}")
    print("=" * 110)

    for tick in range(args.ticks + 1):
        payload = _usage_payload(profiles, current_name)
        current_row = next((r for r in payload["profiles"] if r.get("name") == current_name), None)
        if not current_row:
            print("error: current profile missing from payload")
            return 3

        breached, detail = cli._trigger_breached(current_row, cfg)
        candidate = cli._choose_auto_switch_candidate(payload, cfg)
        candidate_name = str(candidate.get("name")) if isinstance(candidate, dict) and candidate.get("name") else None

        cooldown_left = 0
        if last_switch_tick is not None:
            cooldown_left = max(0, int(args.cooldown_ticks - (tick - last_switch_tick)))

        event = "noop"
        if not breached:
            if pending_due_tick is not None:
                event = "cancel-warning (recovered)"
            pending_due_tick = None
        else:
            if pending_due_tick is None:
                pending_due_tick = tick + int(args.delay_ticks)
                event = f"arm-warning due@{pending_due_tick}"
            elif tick < pending_due_tick:
                event = "waiting-delay"
            elif cooldown_left > 0:
                event = "cooldown-blocked"
            else:
                if candidate_name:
                    current_name = candidate_name
                    last_switch_tick = tick
                    total_switches += 1
                    pending_due_tick = None
                    event = f"SWITCH -> {candidate_name}"
                else:
                    pending_due_tick = None
                    event = "no-candidate"

        now_sec = float(tick * args.tick_seconds)
        event_color = Palette.GREEN if "SWITCH" in event else (Palette.YELLOW if "warning" in event else Palette.DIM)
        print(_c(use_color, f"[t={tick:02d} @{now_sec:6.1f}s] {event}", event_color))
        _print_decision_block(use_color, _usage_payload(profiles, current_name), cfg, prefix="  ")
        if pending_due_tick is not None:
            print(f"  pending_due_tick={pending_due_tick} cooldown_left={cooldown_left}")

        current_profile = _find_profile(profiles, current_name)
        if current_profile is not None:
            current_profile.rem5 = max(0.0, current_profile.rem5 - current_profile.drain5)
            current_profile.remw = max(0.0, current_profile.remw - current_profile.drainw)

        if args.drain_all:
            for p in profiles:
                if p.name == current_name:
                    continue
                p.rem5 = max(0.0, p.rem5 - p.drain5)
                p.remw = max(0.0, p.remw - p.drainw)

        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    print("=" * 110)
    print(f"Simulation complete: switches={total_switches}, final_current={current_name}")
    return 0


def run_real_cycles(args: argparse.Namespace) -> int:
    use_color = _use_color(args.color)
    print(_c(use_color, "Auto-Switch Real Cycle Runner", Palette.BOLD))
    print(
        f"cycles={args.cycles} cycle_sec={args.cycle_sec}s force_switch={_fmt_bool(args.force_switch)} "
        f"restart_app={_fmt_bool(not args.no_restart)}"
    )
    print("=" * 110)

    switched = 0
    for cycle in range(1, args.cycles + 1):
        ts = time.strftime("%H:%M:%S")
        print(_c(use_color, f"[cycle {cycle}/{args.cycles} @ {ts}]", Palette.BLUE))
        try:
            cfg = cli.load_cam_config()
            payload = cli.collect_usage_local_data(timeout_sec=7, config=cfg)
        except Exception as e:
            print(_c(use_color, f"  collect failed: {e}", Palette.RED))
            if cycle < args.cycles:
                time.sleep(max(1.0, args.cycle_sec))
            continue

        if args.prepare_test:
            names = [str(r.get("name")) for r in (payload.get("profiles") or []) if r.get("name")]
            if names:
                current_elig = dict(((cfg.get("profiles") or {}).get("eligibility") or {}))
                merged = dict(current_elig)
                for nm in names:
                    merged[nm] = True
                cfg = cli.update_cam_config(
                    {
                        "auto_switch": {
                            "enabled": True,
                            "same_principal_policy": "allow",
                        },
                        "profiles": {"eligibility": merged},
                    }
                )
                payload = cli.collect_usage_local_data(timeout_sec=7, config=cfg)
                print(_c(use_color, "  prepare-test: enabled eligibility for all profiles (+ allow same principal)", Palette.CYAN))

        breached, _, candidate = _print_decision_block(use_color, payload, cfg, prefix="  ")

        should_switch = bool(candidate) and (bool(args.force_switch) or bool(breached))
        if not should_switch:
            reason = "no candidate" if not candidate else "threshold not breached (use --force-switch)"
            print(_c(use_color, f"  switch skipped: {reason}", Palette.YELLOW))
        else:
            print(_c(use_color, f"  switching now -> {candidate}", Palette.MAGENTA))
            rc = cli.cmd_switch(candidate, restart_codex=(not args.no_restart))
            if rc == 0:
                switched += 1
                print(_c(use_color, "  switch success", Palette.GREEN))
            else:
                print(_c(use_color, f"  switch failed rc={rc}", Palette.RED))

        if cycle < args.cycles:
            print(_c(use_color, f"  sleeping {args.cycle_sec:.1f}s...", Palette.DIM))
            time.sleep(max(1.0, args.cycle_sec))

    print("=" * 110)
    print(_c(use_color, f"Real cycle run complete: switched={switched}/{args.cycles}", Palette.BOLD))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cam-autoswitch-test",
        description="Auto-switch tester with simulation mode and real switch cycle mode.",
    )
    p.add_argument("--mode", choices=["sim", "real"], default="sim", help="sim=logic simulation, real=run real switch cycles")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto", help="ANSI color output mode")

    # Real mode
    p.add_argument("--cycles", type=int, default=6, help="Real mode: number of cycles (default: 6)")
    p.add_argument("--cycle-sec", type=float, default=30.0, help="Real mode: seconds between cycles (default: 30)")
    p.add_argument("--force-switch", action="store_true", help="Real mode: switch even if threshold is not breached")
    p.add_argument("--no-restart", action="store_true", help="Real mode: switch auth without restarting Codex app")
    p.add_argument("--prepare-test", action="store_true", help="Real mode: auto-enable eligibility for all detected profiles and allow same principal")

    # Simulation mode
    p.add_argument("--ticks", type=int, default=16, help="Simulation mode: how many evaluation ticks to run")
    p.add_argument("--tick-seconds", type=float, default=5.0, help="Simulation mode: simulated seconds per tick")
    p.add_argument("--sleep-sec", type=float, default=0.0, help="Simulation mode: real sleep per tick")
    p.add_argument("--threshold-5h", type=int, default=30, help="5h threshold percentage")
    p.add_argument("--threshold-weekly", type=int, default=20, help="weekly threshold percentage")
    p.add_argument("--trigger-mode", choices=["any", "all"], default="any", help="Trigger mode")
    p.add_argument("--ranking-mode", choices=["balanced", "max_5h", "max_weekly", "manual"], default="balanced", help="Ranking mode")
    p.add_argument("--delay-ticks", type=int, default=1, help="Simulation mode: delay ticks before switch")
    p.add_argument("--cooldown-ticks", type=int, default=2, help="Simulation mode: cooldown ticks")
    p.add_argument("--start", choices=["alpha", "beta", "gamma"], default="alpha", help="Simulation mode: starting profile")
    p.add_argument("--drain-all", action="store_true", help="Simulation mode: drain non-current profiles too")

    p.add_argument("--alpha-5h", type=float, default=34.0)
    p.add_argument("--alpha-weekly", type=float, default=68.0)
    p.add_argument("--alpha-drain-5h", type=float, default=6.0)
    p.add_argument("--alpha-drain-weekly", type=float, default=0.5)

    p.add_argument("--beta-5h", type=float, default=82.0)
    p.add_argument("--beta-weekly", type=float, default=90.0)
    p.add_argument("--beta-drain-5h", type=float, default=2.0)
    p.add_argument("--beta-drain-weekly", type=float, default=0.4)

    p.add_argument("--gamma-5h", type=float, default=76.0)
    p.add_argument("--gamma-weekly", type=float, default=78.0)
    p.add_argument("--gamma-drain-5h", type=float, default=1.5)
    p.add_argument("--gamma-drain-weekly", type=float, default=0.3)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    args.cycles = max(1, int(args.cycles))
    args.cycle_sec = max(1.0, float(args.cycle_sec))
    args.delay_ticks = max(0, int(args.delay_ticks))
    args.cooldown_ticks = max(0, int(args.cooldown_ticks))
    args.ticks = max(1, int(args.ticks))
    args.tick_seconds = max(0.1, float(args.tick_seconds))
    args.sleep_sec = max(0.0, float(args.sleep_sec))

    if args.mode == "real":
        return run_real_cycles(args)
    return run_simulation(args)


if __name__ == "__main__":
    raise SystemExit(main())
