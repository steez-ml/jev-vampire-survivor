"""Read a run log and report the benchmark numbers.

    python -m vampirejev.summary path\\to\\run.jsonl

Survival time, level at minutes 5, 10, and 15 (blank if the run ended earlier),
HP lost per minute (drops only; healing is not subtracted), and why the run ended.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


def summarize(path: Path) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    outcome: dict[str, Any] | None = None
    meta: dict[str, Any] = {}
    disarms = 0
    unfocused = 0
    jev_calls = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("kind")
            if kind == "meta":
                meta = row
            elif kind == "sample":
                samples.append(row)
            elif kind == "outcome":
                outcome = row
            elif kind == "gate" and row.get("event") == "disarm":
                disarms += 1
            elif kind == "gate" and row.get("event") == "unfocused":
                unfocused += 1
            elif kind == "jev":
                jev_calls += 1
    survived = _survived(samples, outcome)
    return {
        "path": str(path),
        "controller": meta.get("controller", ""),
        "cards": meta.get("cards", ""),
        "starter": meta.get("starter", ""),
        "model": meta.get("model", ""),
        "save_note": meta.get("save_note", ""),
        "survived_s": survived,
        "level_m5": _level_at(samples, 5 * 60),
        "level_m10": _level_at(samples, 10 * 60),
        "level_m15": _level_at(samples, 15 * 60),
        "hp_lost_per_min": _hp_lost_per_min(samples, survived),
        "cause": (outcome or {}).get("reason", ""),
        "disarms": disarms,
        "unfocused": unfocused,
        "jev_calls": jev_calls,
        "hands_off": disarms == 0 and unfocused == 0 and survived > 0,
    }


def format_summary(row: dict[str, Any]) -> str:
    def level(value: Optional[int]) -> str:
        return "-" if value is None else str(value)

    return (
        f"{row['controller'] or '-'} starter={row['starter'] or '-'} "
        f"survived={row['survived_s']:.0f}s "
        f"lv@5={level(row['level_m5'])} lv@10={level(row['level_m10'])} lv@15={level(row['level_m15'])} "
        f"hp_lost/min={row['hp_lost_per_min']:.1f} cause={row['cause'] or '-'} "
        f"disarms={row['disarms']} unfocused={row['unfocused']} jev_calls={row['jev_calls']} "
        f"hands_off={int(row['hands_off'])}"
    )


def _survived(samples: list[dict[str, Any]], outcome: dict[str, Any] | None) -> float:
    times = [float(row.get("t") or 0.0) for row in samples]
    if outcome is not None and outcome.get("t") is not None:
        times.append(float(outcome["t"]))
    return max(times) if times else 0.0


def _level_at(samples: list[dict[str, Any]], second: float) -> Optional[int]:
    reached = [row for row in samples if float(row.get("t") or 0.0) >= second and row.get("level") is not None]
    if not reached:
        if not samples or float(samples[-1].get("t") or 0.0) < second:
            return None
        return None
    return int(reached[0]["level"])


def _hp_lost_per_min(samples: list[dict[str, Any]], survived: float) -> float:
    lost = 0.0
    previous: float | None = None
    for row in samples:
        if row.get("hp") is None:
            continue
        hp = float(row["hp"])
        if previous is not None and hp < previous:
            lost += previous - hp
        previous = hp
    minutes = survived / 60.0
    if minutes <= 1e-6:
        return 0.0
    return lost / minutes


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m vampirejev.summary <run.jsonl>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    print(format_summary(summarize(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
