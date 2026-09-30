"""UDP receiver for v2 snapshots. Sequence numbers drive Hz and drop stats."""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Optional

from .snapshot import GameState

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("VSJEV_UDP_PORT", "27182"))


@dataclass
class RecvStats:
    received: int = 0
    drops: int = 0
    last_seq: int = 0
    hz: float = 0.0
    last_error: str = ""


class SnapshotReceiver:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.stats = RecvStats()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self._sock.settimeout(0.05)
        self._window_start = time.monotonic()
        self._window_count = 0

    def poll(self) -> Optional[GameState]:
        try:
            data, _addr = self._sock.recvfrom(65535)
        except socket.timeout:
            return None
        except OSError as exc:
            self.stats.last_error = str(exc)
            return None

        try:
            snapshot = GameState.from_json(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            self.stats.last_error = str(exc)
            return None

        self._note(snapshot.seq)
        return snapshot

    def close(self) -> None:
        self._sock.close()

    def _note(self, seq: int) -> None:
        if self.stats.last_seq > 0 and seq > self.stats.last_seq + 1:
            self.stats.drops += seq - self.stats.last_seq - 1
        self.stats.last_seq = seq
        self.stats.received += 1
        self._window_count += 1
        now = time.monotonic()
        elapsed = now - self._window_start
        if elapsed >= 1.0:
            self.stats.hz = self._window_count / elapsed
            self._window_count = 0
            self._window_start = now
