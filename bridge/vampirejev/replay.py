"""Replay a JSONL recording through the pilot and summarise what it would have done.

    python -m vampirejev.replay ..\recordings\game-state.v3.jsonl [--every 1.0] [--mode kite]

Recordings come from the BepInEx flag ``Telemetry.RecordJsonl`` (10 Hz). The replay cannot move
the player, so "keys held" is approximated by the pilot's own previous command — good enough to
see mode changes, vetoes, wall bumps the tracker would have flagged, and heading choices over time.
Use it to compare two policy versions on the same run before touching the game.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .pilot import Pilot
from .polar import SECTOR_NAMES
from .policy import MODES, describe
from .snapshot import GameState
from .wasd import heading_to_keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a v3/v4 JSONL recording through the pilot.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--every", type=float, default=1.0, help="seconds between printed rows (default 1.0)")
    parser.add_argument("--mode", choices=sorted(MODES), default=None, help="lock a mode")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 2

    pilot = Pilot(mode_lock=args.mode)
    keys: frozenset[str] = frozenset()
    headings: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    vetoes: Counter[str] = Counter()
    rows = 0
    bad = 0
    last_print = float("-inf")
    first_t = None
    last_snapshot = None
    with args.path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                snapshot = GameState.from_json(line)
            except (ValueError, TypeError):
                bad += 1
                continue
            rows += 1
            t = snapshot.t_ms / 1000.0
            if first_t is None:
                first_t = t
            out = pilot.step(snapshot, keys, t)
            keys = heading_to_keys(out.command.dx, out.command.dy)
            headings[out.command.heading] += 1
            modes[out.mode] += 1
            for i, vetoed in enumerate(out.decision.vetoed):
                if vetoed:
                    vetoes[SECTOR_NAMES[i]] += 1
            last_snapshot = snapshot
            if not args.quiet and t - last_print >= args.every:
                last_print = t
                player = snapshot.player
                hp = f"{player.hp:.0f}/{player.hp_max:.0f}" if player else "—"
                lv = f" lv={player.level}" if player and player.level is not None else ""
                blocked = "".join(sorted(out.blocked)) or "-"
                print(
                    f"t={t - first_t:7.1f} run={snapshot.run.survived_seconds:6.1f} hp={hp}{lv} "
                    f"{describe(snapshot, out.command, out.decision)} blocked={blocked} stuck={int(out.stuck)}"
                )

    print()
    print(f"rows={rows} bad={bad} stuck_events={pilot.tracker.events} walls_remembered={len(pilot.memory)}")
    print("headings:", ", ".join(f"{k}={v}" for k, v in headings.most_common()))
    print("modes:   ", ", ".join(f"{k}={v}" for k, v in modes.most_common()))
    print("vetoes:  ", ", ".join(f"{k}={v}" for k, v in vetoes.most_common()) or "none")
    if last_snapshot is not None and last_snapshot.player is not None:
        player = last_snapshot.player
        print(f"final: survived={last_snapshot.run.survived_seconds:.1f}s hp={player.hp:.0f} level={player.level}")
        if player.weapons:
            print("weapons:", ", ".join(f"{w.type}:{w.level}" for w in player.weapons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
