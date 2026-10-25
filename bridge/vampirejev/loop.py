"""Receive snapshots, run a controller, and send gated keys.

`--controller baseline` is today's pilot. `code` and `jev` use the navigator:
code lists options and a plain picker chooses, jev does the same and may replace
the pick when an answer is fresh and confident. The motor is the only thing
that presses movement keys. Menu keys, if enabled, are a separate driver and
only fire on a card screen.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from .gate import arm_key_down, game_window_focused, human_disarms, physical_wasd_down, should_send, snapshot_playable
from .hud import clear_overlay_input, write_overlay_input
from .jevclient import PINNED_MODEL
from .menu import MenuDriver, MenuExecutor
from .mind import Mind, MindOutput
from .pilot import Pilot, PilotOutput
from .policy import MODES, Command, describe
from .receiver import DEFAULT_PORT, SnapshotReceiver
from .runlog import RunLog
from .snapshot import GameState
from .wasd import WasdDriver, heading_to_keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VampireJev loop: read snapshots, decide, send gated keys.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port (default 27182)")
    parser.add_argument("--hold-ctrl", action="store_true", help="Hold Ctrl to stay armed. Default is tap Ctrl to toggle.")
    parser.add_argument("--arm-toggle", action="store_true", help="Deprecated: toggle is now the default.")
    parser.add_argument("--mode", choices=sorted(MODES), default=None, help="Lock the baseline pilot into one mode.")
    parser.add_argument("--no-body-flags", action="store_true", help="Ignore the game's body blocked flags.")
    parser.add_argument("--controller", choices=("baseline", "code", "jev"), default="baseline")
    parser.add_argument("--cards", choices=("off", "rules", "jev"), default="off")
    parser.add_argument(
        "--menu-keys",
        choices=("off", "provisional"),
        default="off",
        help="provisional presses an unverified key plan on card screens. Leave off until those keys are confirmed.",
    )
    parser.add_argument("--starter", default="", help="Character name recorded in the run log. The snapshot does not include it yet.")
    parser.add_argument("--save-note", default="", help="PowerUps, Arcanas, Hyper, Hurry. Recorded in the run log.")
    parser.add_argument("--model", default=PINNED_MODEL, help="Jev model id. Provisional until the probe is run.")
    parser.add_argument("--log-dir", default="", help="Directory for per-run JSONL logs. Default: recordings/runs")
    args = parser.parse_args(argv)
    toggle = not args.hold_ctrl

    print("VampireJev loop starting. This process is required - the game plugin does not steer.", file=sys.stderr)
    if toggle:
        print("Click Vampire Survivors, then tap Ctrl once to arm. Tap Ctrl again to disarm.", file=sys.stderr)
    else:
        print("Click the Vampire Survivors window, then hold Ctrl to arm. Default is SAFE.", file=sys.stderr)
    print(f"Controller {args.controller}, cards {args.cards}, menu keys {args.menu_keys}.", file=sys.stderr)
    if args.mode:
        print(f"Mode locked to {args.mode}.", file=sys.stderr)

    receiver = SnapshotReceiver(port=args.port)
    driver = WasdDriver()
    menu = MenuDriver()
    menu_exec = MenuExecutor()
    pilot: Optional[Pilot] = None
    mind: Optional[Mind] = None
    if args.controller == "baseline":
        pilot = Pilot(mode_lock=args.mode, use_body_flags=not args.no_body_flags)
    else:
        mind = Mind(controller=args.controller, cards=args.cards, model=args.model)
    log = RunLog(
        Path(args.log_dir) if args.log_dir else Path(__file__).resolve().parents[2] / "recordings" / "runs",
        {
            "controller": args.controller,
            "cards": args.cards,
            "starter": args.starter,
            "model": args.model if args.controller == "jev" or args.cards == "jev" else "",
            "save_note": args.save_note,
            "menu_keys": args.menu_keys,
        },
    )
    snapshot: Optional[GameState] = None
    out: Optional[PilotOutput] = None
    mind_out: Optional[MindOutput] = None
    armed = False
    was_armed = False
    was_focused = False
    toggle_latched = False
    last_status = 0.0
    last_sample = 0.0
    try:
        while True:
            incoming = receiver.poll()
            now = time.monotonic()
            if incoming is not None or (out is None and mind_out is None):
                if incoming is not None:
                    snapshot = incoming
                if pilot is not None:
                    out = pilot.step(snapshot, driver.down, now)
                    command = out.command
                else:
                    assert mind is not None
                    mind_out = mind.step(snapshot, driver.down, now)
                    command = mind_out.command
            else:
                command = out.command if out is not None else mind_out.command  # type: ignore[union-attr]

            _track_run(log, snapshot)
            if mind_out is not None and mind_out.events:
                for event in mind_out.events:
                    log.event(**event)
                mind_out.events.clear()

            if toggle:
                held = arm_key_down()
                if held and not toggle_latched:
                    armed = not armed
                toggle_latched = held
            else:
                armed = arm_key_down()

            wanted = heading_to_keys(command.dx, command.dy)
            focused = game_window_focused()
            overridden = human_disarms(snapshot, wanted, physical_wasd_down(), driver.down)
            if overridden:
                armed = False
                driver.all_up()
            elif should_send(armed, focused, snapshot):
                driver.apply(command.dx, command.dy)
            else:
                driver.all_up()

            if args.menu_keys == "provisional" and mind_out is not None and armed and focused and not snapshot_playable(snapshot):
                signature = mind_out.card_line
                menu_exec.step(now, signature, mind_out.card_keys, menu)

            if log.active and was_armed and not armed:
                log.event("gate", event="disarm", why="user-wasd" if overridden else "toggle", t=_survived(snapshot))
            if log.active and was_focused and not focused:
                log.event("gate", event="unfocused", t=_survived(snapshot))
            if log.active and snapshot is not None and snapshot.run.paused:
                pass
            was_armed = armed
            was_focused = focused

            if pilot is not None and out is not None:
                why = _why(armed, focused, overridden, snapshot, command, driver.down, out)
                blocked = "".join(sorted(out.blocked)) if armed else ""
                mode = out.mode if armed else ""
                write_overlay_input(
                    armed,
                    driver.down,
                    command.heading,
                    focused,
                    why,
                    mode,
                    blocked,
                    {"controller": "baseline", "decider": "pilot", "option": mode},
                )
            elif mind_out is not None:
                why = _why_mind(armed, focused, overridden, snapshot, command, driver.down, mind_out)
                blocked = "".join(sorted(mind_out.blocked)) if armed else ""
                write_overlay_input(
                    armed,
                    driver.down,
                    command.heading,
                    focused,
                    why,
                    mind_out.mode if armed else "",
                    blocked,
                    _mind_fields(mind_out),
                )
            else:
                why = "no-snapshot"

            if now - last_status >= 1.0:
                last_status = now
                _print_status(snapshot, receiver, armed, focused, why, command, driver, out, mind_out, pilot)
            if log.active and snapshot is not None and now - last_sample >= 1.0:
                last_sample = now
                _sample(log, snapshot, mind_out)
    except KeyboardInterrupt:
        print("loop stopping", file=sys.stderr)
        _finish(log, snapshot, "stopped")
        return 0
    finally:
        driver.all_up()
        clear_overlay_input()
        receiver.close()
        if mind is not None:
            mind.close()
        _finish(log, snapshot, "stopped")
        log.close()


def _track_run(log: RunLog, snapshot: Optional[GameState]) -> None:
    if snapshot is None:
        return
    player = snapshot.player
    alive = player is None or player.hp > 0
    if snapshot.run.running and alive and not log.active and snapshot.run.survived_seconds < 1800:
        log.begin(snapshot.run.survived_seconds, snapshot.seq)
    if not log.active:
        return
    level = player.level if player else None
    hp = player.hp if player else None
    if player is not None and player.hp <= 0:
        log.end("hp-zero", snapshot.run.survived_seconds, level, hp)
    elif snapshot.run.survived_seconds >= 1800:
        log.end("cleared", snapshot.run.survived_seconds, level, hp)
    elif not snapshot.run.running:
        log.end("left-run", snapshot.run.survived_seconds, level, hp)


def _finish(log: RunLog, snapshot: Optional[GameState], reason: str) -> None:
    if not log.active:
        return
    level = snapshot.player.level if snapshot and snapshot.player else None
    hp = snapshot.player.hp if snapshot and snapshot.player else None
    survived = snapshot.run.survived_seconds if snapshot else 0.0
    log.end(reason, survived, level, hp)


def _survived(snapshot: Optional[GameState]) -> float:
    return snapshot.run.survived_seconds if snapshot else 0.0


def _sample(log: RunLog, snapshot: GameState, mind_out: Optional[MindOutput]) -> None:
    player = snapshot.player
    if player is None:
        return
    log.event(
        "sample",
        t=snapshot.run.survived_seconds,
        hp=player.hp,
        hp_max=player.hp_max,
        level=player.level,
        xp=player.xp,
        decider=mind_out.decider if mind_out else "pilot",
        option=mind_out.option_id if mind_out else "",
        fallback=mind_out.fallback_share if mind_out else None,
    )


def _mind_fields(mind_out: MindOutput) -> dict[str, str]:
    fields = {
        "controller": mind_out.controller,
        "decider": mind_out.decider,
        "confidence": "" if mind_out.confidence is None else f"{mind_out.confidence:.2f}",
        "latency_ms": "" if mind_out.latency_ms is None else f"{mind_out.latency_ms:.0f}",
        "fallback": f"{mind_out.fallback_share:.2f}",
        "stance": mind_out.stance,
        "option": mind_out.option_id,
        "mark": str(mind_out.mark_sector),
        "card": mind_out.card_line,
        "model": mind_out.model,
    }
    for index, option in enumerate(mind_out.options[:8]):
        fields[f"opt{index}"] = f"{option.id}|{option.facts}"
    return fields


def _print_status(snapshot, receiver, armed, focused, why, command, driver, out, mind_out, pilot) -> None:
    seq = snapshot.seq if snapshot else 0
    probe = snapshot.perf.probe_us if snapshot else 0
    mode = "ARMED" if armed else "SAFE"
    keys = "".join(sorted(driver.down)) or "-"
    run = snapshot.run if snapshot else None
    flags = (
        f"running={int(run.running)} paused={int(run.paused)} level_up={int(run.level_up)}"
        if run is not None
        else "running=? paused=? level_up=?"
    )
    if out is not None and pilot is not None:
        detail = f"{describe(snapshot, command, out.decision)} {_pilot_status(snapshot, out, pilot)}"
    elif mind_out is not None:
        detail = (
            f"controller={mind_out.controller} decider={mind_out.decider} option={mind_out.option_id or '-'} "
            f"stance={mind_out.stance or '-'} heading={command.heading}"
        )
    else:
        detail = ""
    print(
        f"{mode} why={why} focused={int(focused)} {flags} seq={seq} recv_hz={receiver.stats.hz:.1f} "
        f"drops={receiver.stats.drops} probe_us={probe} {detail} keys={keys}",
        file=sys.stderr,
    )


def _pilot_status(snapshot: Optional[GameState], out: PilotOutput, pilot: Pilot) -> str:
    blocked = "".join(sorted(out.blocked)) or "-"
    remembered = "".join(sorted(out.remembered)) or "-"
    text = f"blocked={blocked} remembered={remembered} walls_mem={len(pilot.memory)} stuck_events={pilot.tracker.events}"
    if snapshot is not None and snapshot.player is not None:
        player = snapshot.player
        if player.level is not None:
            text += f" lv={player.level} xp={player.xp_frac:.2f}"
        if player.weapons:
            text += " weapons=" + ",".join(f"{w.type}:{w.level}" for w in player.weapons[:6])
        if player.has_blocked:
            text += " body=" + ("".join(sorted(player.blocked)) or "-")
            if out.body_y_flipped is not None:
                text += f" yflip={int(out.body_y_flipped)}"
        if snapshot.polar.wall is not None:
            text += f" wall_cells={sum(1 for v in snapshot.polar.wall if v > 0.001)} tilemaps={snapshot.counts.tilemaps}"
        if snapshot.pickups:
            text += " pickups=" + ",".join(p.type for p in snapshot.pickups[:6])
        if snapshot.destructibles:
            text += " loot=" + ",".join(d.type for d in snapshot.destructibles[:6])
    return text


def _why(
    armed: bool,
    focused: bool,
    overridden: bool,
    snapshot: Optional[GameState],
    command: Command,
    keys: frozenset[str],
    out: PilotOutput,
) -> str:
    if overridden:
        return "user-wasd"
    if snapshot is None:
        return "no-snapshot"
    if not snapshot.run.running:
        return "menu"
    if snapshot.run.level_up:
        return "level-up"
    if snapshot.run.paused:
        return "paused"
    if not armed:
        return "safe"
    if not focused:
        return "unfocused"
    if not snapshot_playable(snapshot):
        return "blocked"
    if command.is_idle and not keys:
        return "idle"
    if out.stuck:
        return "stuck"
    return "send"


def _why_mind(
    armed: bool,
    focused: bool,
    overridden: bool,
    snapshot: Optional[GameState],
    command: Command,
    keys: frozenset[str],
    mind_out: MindOutput,
) -> str:
    if overridden:
        return "user-wasd"
    if snapshot is None:
        return "no-snapshot"
    if not snapshot.run.running:
        return "menu"
    if snapshot.run.level_up or (snapshot.card_screen is not None and snapshot.card_screen.kind != "chest"):
        return "level-up"
    if snapshot.run.paused or (snapshot.card_screen is not None and snapshot.card_screen.kind == "chest"):
        return "paused"
    if not armed:
        return "safe"
    if not focused:
        return "unfocused"
    if command.is_idle and not keys:
        return "idle"
    if mind_out.reflex:
        return "reflex"
    if mind_out.stuck:
        return "stuck"
    return "send"


if __name__ == "__main__":
    raise SystemExit(main())
