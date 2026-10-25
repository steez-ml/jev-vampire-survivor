"""Background Jev calls, and the request built from the current options.

The fast loop never waits on this thread. It submits the latest options and
reads whatever answer is already sitting there. Card requests jump the queue
because the game is paused and the movement answer does not matter until the
screen closes.
"""

from __future__ import annotations

import asyncio
import random
import sys
import threading
import time
from typing import Any

from .cards import card_question
from .jevclient import CARD_TIMEOUT_S, NAV_TIMEOUT_S, JevRequest, JevResult, MissingApiKey
from .options import Option
from .perception import Perception
from .snapshot import CardScreen, GameState
from .words import weapon_sentence

MOVEMENT_INSTRUCTIONS = "Which option would a strong player take next?"
CARD_INSTRUCTIONS = "Which offered card would a strong player take?"
CALL_INTERVAL_S = 0.34


def movement_request(snapshot: GameState, perception: Perception, options: list[Option], now: float, rng: random.Random) -> JevRequest:
    order = [item.id for item in options]
    rng.shuffle(order)
    facts = {item.id: item.facts for item in options}
    player = snapshot.player
    weapons = [weapon_sentence(weapon) for weapon in player.weapons] if player is not None else []
    state = {
        "player": {
            "hp": perception.hp_band,
            "minute": perception.minute,
            "level": perception.level if perception.level is not None else "unknown",
            "next_level": perception.next_level,
        },
        "weapons": weapons,
        "trend": perception.trend,
        "boss": "nearby" if perception.boss_present else "none",
    }
    return JevRequest(
        kind="movement",
        state=state,
        question_id="next",
        instructions=MOVEMENT_INSTRUCTIONS,
        criteria={item: facts[item] for item in order},
        option_order=order,
        include_play_safe=True,
        built_mono=now,
        snapshot_t_ms=snapshot.t_ms,
        timeout_s=NAV_TIMEOUT_S,
    )


def card_request(snapshot: GameState, screen: CardScreen, now: float, rng: random.Random) -> JevRequest | None:
    player = snapshot.player
    if player is None or not screen.offers:
        return None
    state, criteria = card_question(screen, player.weapons, player.passives, snapshot.evolutions)
    order = list(criteria)
    rng.shuffle(order)
    criteria = {item: criteria[item] for item in order}
    return JevRequest(
        kind="card",
        state=state,
        question_id="card",
        instructions=CARD_INSTRUCTIONS,
        criteria=criteria,
        option_order=order,
        include_play_safe=False,
        built_mono=now,
        snapshot_t_ms=snapshot.t_ms,
        timeout_s=CARD_TIMEOUT_S,
    )


class JevBackground:
    def __init__(self, client: Any, interval_s: float = CALL_INTERVAL_S) -> None:
        self.client = client
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._movement_pending: JevRequest | None = None
        self._card_pending: JevRequest | None = None
        self.movement: JevResult | None = None
        self.card: JevResult | None = None
        self._disabled = ""

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="jev", daemon=True)
        self._thread.start()

    def submit(self, request: JevRequest) -> None:
        with self._lock:
            if request.kind == "card":
                self._card_pending = request
            else:
                self._movement_pending = request

    def latest(self, kind: str) -> JevResult | None:
        with self._lock:
            return self.card if kind == "card" else self.movement

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            request = self._take()
            if request is None or self._disabled:
                await asyncio.sleep(0.05)
                continue
            started = time.monotonic()
            try:
                result = await self.client.ask(request)
            except MissingApiKey as exc:
                self._disabled = str(exc)
                print(self._disabled + ". Jev calls are off until the key is set. The code picker will decide.", file=sys.stderr)
                result = JevResult(
                    ok=False,
                    kind=request.kind,
                    error=self._disabled,
                    option_order=list(request.option_order),
                    state=dict(request.state),
                    criteria=dict(request.criteria),
                    built_mono=request.built_mono,
                    snapshot_t_ms=request.snapshot_t_ms,
                    latency_s=time.monotonic() - started,
                )
            except Exception as exc:
                result = JevResult(
                    ok=False,
                    kind=request.kind,
                    error=f"{type(exc).__name__}: {exc}",
                    option_order=list(request.option_order),
                    state=dict(request.state),
                    criteria=dict(request.criteria),
                    built_mono=request.built_mono,
                    snapshot_t_ms=request.snapshot_t_ms,
                    latency_s=time.monotonic() - started,
                )
            with self._lock:
                if request.kind == "card":
                    self.card = result
                else:
                    self.movement = result
            if request.kind != "card":
                remain = self.interval_s - (time.monotonic() - started)
                if remain > 0:
                    await asyncio.sleep(remain)

    def _take(self) -> JevRequest | None:
        with self._lock:
            if self._card_pending is not None:
                request = self._card_pending
                self._card_pending = None
                return request
            request = self._movement_pending
            self._movement_pending = None
            return request


def sync_ask(client: Any, request: JevRequest) -> JevResult:
    """Run one call on the calling thread. Tests use this so they never start a background thread."""
    try:
        return asyncio.run(client.ask(request))
    except Exception as exc:
        return JevResult(
            ok=False,
            kind=request.kind,
            error=f"{type(exc).__name__}: {exc}",
            option_order=list(request.option_order),
            built_mono=request.built_mono,
            snapshot_t_ms=request.snapshot_t_ms,
        )
