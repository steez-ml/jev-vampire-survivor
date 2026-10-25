"""One JSONL file per run. This is the bridge's log, separate from the mod's raw snapshot recording.

Each line is one JSON object. Jev sees none of this. The file is how we later
tell a lucky run from a pick that actually helped: the question, the answer,
who acted, and what HP and XP did before the next pick.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class RunLog:
    def __init__(self, directory: Path, meta: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = directory / f"run-{stamp}.jsonl"
        self.meta = dict(meta)
        self._fh = self.path.open("w", encoding="utf-8")
        self.active = False

    def begin(self, survived: float, seq: int) -> None:
        if self.active:
            return
        self.active = True
        self.event("meta", t=survived, seq=seq, **self.meta)

    def end(self, reason: str, survived: float, level: Optional[int], hp: Optional[float]) -> None:
        if not self.active:
            return
        self.event("outcome", reason=reason, t=survived, level=level, hp=hp)
        self.active = False

    def event(self, kind: str, **fields: Any) -> None:
        if not self.active and kind not in {"meta", "outcome"}:
            return
        record = {"kind": kind, **fields}
        self._fh.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass
