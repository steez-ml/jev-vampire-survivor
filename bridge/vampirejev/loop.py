"""Receive snapshots, run the polar pilot, and send gated WASD."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from .gate import arm_key_down, game_window_focused, physical_wasd_down, should_send, snapshot_playable, user_wasd_override
from .hud import clear_overlay_input, write_overlay_input
from .pilot import Pilot, PilotOutput
from .policy import MODES, Command, describe
from .receiver import DEFAULT_PORT, SnapshotReceiver
from .snapshot import GameState
from .wasd import WasdDriver, heading_to_keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VampireJev loop: polar pilot, gated WASD.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port (default 27182)")
    parser.add_argument(
        "--hold-ctrl",
        action="store_true",
        help="Hold Ctrl to stay armed (old behavior). Default is tap Ctrl to toggle.",
    )
    parser.add_argument(
        "--arm-toggle",
        action="store_true",
        help="Deprecated: toggle is now the default.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        default=None,
        help="Lock the pilot into one mode (farm/kite/flee/chest) for A/B runs. Default: automatic.",
    )
    parser.add_argument(
        "--no-body-flags",
        action="store_true",
        help="Ignore the game's body blocked flags; rely on the displacement stuck detector only.",
    )
    args = parser.parse_args(argv)
    toggle = not args.hold_ctrl

    print("VampireJev loop starting. This process is required — the game plugin does not steer.", file=sys.stderr)
    if toggle:
        print("Click Vampire Survivors, then tap Ctrl once to arm. Tap Ctrl again to disarm.", file=sys.stderr)
    else:
        print("Click the Vampire Survivors window, then hold Ctrl to arm. Default is SAFE.", file=sys.stderr)
    if args.mode:
        print(f"Mode locked to {args.mode}.", file=sys.stderr)
    receiver = SnapshotReceiver(port=args.port)
    driver = WasdDriver()
    pilot = Pilot(mode_lock=args.mode, use_body_flags=not args.no_body_flags)
    snapshot = None
    out: Optional[PilotOutput] = None
    armed = False
    toggle_latched = False
    last_status = 0.0
    try:
        while True:
            incoming = receiver.poll()
            now = time.monotonic()
            if incoming is not None or out is None:
                if incoming is not None:
                    snapshot = incoming
                # One pilot step per snapshot. The keys we are holding right now are what moved the
                # player since the previous snapshot, which is what the stuck detector needs.
                out = pilot.step(snapshot, driver.down, now)

            if toggle:
                held = arm_key_down()
                if held and not toggle_latched:
                    armed = not armed
                toggle_latched = held
            else:
                armed = arm_key_down()

            command = out.command
            wanted = heading_to_keys(command.dx, command.dy)
            focused = game_window_focused()
            overridden = user_wasd_override(wanted, physical_wasd_down(), driver.down)
            if overridden:
                armed = False
                driver.all_up()
            elif should_send(armed, focused, snapshot):
                driver.apply(command.dx, command.dy)
            else:
                driver.all_up()

            why = _why(armed, focused, overridden, snapshot, command, driver.down, out)
            blocked = "".join(sorted(out.blocked)) if armed else ""
            write_overlay_input(armed, driver.down, command.heading, focused, why, out.mode if armed else "", blocked)

            if now - last_status >= 1.0:
                last_status = now
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
                print(
                    f"{mode} why={why} focused={int(focused)} {flags} seq={seq} recv_hz={receiver.stats.hz:.1f} "
                    f"drops={receiver.stats.drops} probe_us={probe} {describe(snapshot, command, out.decision)} "
                    f"{_pilot_status(snapshot, out, pilot)} keys={keys}",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        print("loop stopping", file=sys.stderr)
        return 0
    finally:
        driver.all_up()
        clear_overlay_input()
        receiver.close()


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


if __name__ == "__main__":
    raise SystemExit(main())
