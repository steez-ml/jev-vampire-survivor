"""One tick of the new controller: perceive, list options, pick, steer.

`--controller code` stops after the code picker. `--controller jev` asks Jev in the
background and uses that pick only when the arbiter accepts it. Either way the
motor is the only thing that produces a heading.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .arbiter import accept_choice, fresh_play_safe
from .cards import decide_cards
from .gate import snapshot_playable
from .jevclient import PINNED_MODEL, TypeSafeJevClient
from .motor import Motor
from .navigator import JevBackground, card_request, movement_request, sync_ask
from .options import Option, build_options
from .perception import PerceptionMemory, perceive
from .picker import CodePicker
from .policy import Command
from .polar import SECTOR_NAMES
from .snapshot import CardScreen, GameState


@dataclass
class MindOutput:
    command: Command
    controller: str
    decider: str
    mode: str
    option_id: str = ""
    stance: str = ""
    facts: str = ""
    options: list[Option] = field(default_factory=list)
    confidence: Optional[float] = None
    latency_ms: Optional[float] = None
    fallback_share: float = 0.0
    reflex: bool = False
    mark_sector: int = -1
    blocked: frozenset[str] = frozenset()
    remembered: frozenset[str] = frozenset()
    stuck: bool = False
    body_y_flipped: Optional[bool] = None
    card_line: str = ""
    card_keys: tuple[str, ...] = ()
    model: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


class Mind:
    def __init__(
        self,
        controller: str = "code",
        cards: str = "off",
        client: Any = None,
        sync: bool = False,
        model: str = PINNED_MODEL,
    ) -> None:
        self.controller = controller
        self.cards = cards
        self.sync = sync
        self.model = model
        self.motor = Motor()
        self.picker = CodePicker()
        self.memory = PerceptionMemory()
        self.rng = random.Random()
        self.commit_id: str | None = None
        self.commit_source = "code"
        self._ticks = 0
        self._fallback = 0
        self._logged_move: Any = None
        self._logged_card: Any = None
        self._card_sig = ""
        self._card_result = None
        self.background: JevBackground | None = None
        self.client = client
        if controller == "jev" or cards == "jev":
            self.client = client if client is not None else TypeSafeJevClient(model)
            if not sync:
                self.background = JevBackground(self.client)
                self.background.start()

    def close(self) -> None:
        if self.background is not None:
            self.background.close()
            self.background = None

    def step(self, snapshot: Optional[GameState], sent_keys: Iterable[str], now: float) -> MindOutput:
        events: list[dict[str, Any]] = []
        if snapshot is None or snapshot.player is None or not snapshot.run.running:
            self.motor.tracker.reset()
            return self._idle("no-run")

        perception = perceive(snapshot, self.memory)
        options = build_options(snapshot, perception) if snapshot_playable(snapshot) else []
        by_id = {item.id: item for item in options}

        movement = self._movement_result(snapshot, perception, options, now, events)
        play_safe = fresh_play_safe(movement, now)
        accepted = accept_choice(movement, set(by_id), now) if self.controller == "jev" else None
        self._commit(accepted, by_id, options, snapshot)
        chosen = by_id.get(self.commit_id or "")
        steer = self.motor.step(snapshot, chosen if snapshot_playable(snapshot) else None, perception, sent_keys, play_safe)

        if steer.note == "nudge":
            decider = "nudge"
        elif steer.reflex:
            decider = "reflex"
        elif self.controller == "jev" and self.commit_source == "jev" and chosen is not None:
            decider = "jev"
        else:
            decider = "code"

        if snapshot_playable(snapshot):
            self._ticks += 1
            if decider != "jev":
                self._fallback += 1

        card_line, card_keys = self._cards(snapshot, now, events)
        heading = steer.command.heading
        mark = SECTOR_NAMES.index(heading) if heading in SECTOR_NAMES else -1
        confidence = movement.confidence if movement is not None and movement.ok else None
        latency = movement.latency_s * 1000.0 if movement is not None and movement.ok else None
        model = movement.model if movement is not None and movement.model else self.model
        return MindOutput(
            command=steer.command,
            controller=self.controller,
            decider=decider,
            mode=chosen.stance if chosen is not None else "",
            option_id=chosen.id if chosen is not None else "",
            stance=chosen.stance if chosen is not None else "",
            facts=chosen.facts if chosen is not None else "",
            options=options,
            confidence=confidence,
            latency_ms=latency,
            fallback_share=(self._fallback / self._ticks) if self._ticks else 0.0,
            reflex=steer.reflex,
            mark_sector=mark,
            blocked=steer.blocked,
            remembered=steer.remembered,
            stuck=steer.stuck,
            body_y_flipped=steer.body_y_flipped,
            card_line=card_line,
            card_keys=card_keys,
            model=model,
            events=events,
        )

    def _commit(self, accepted: str | None, by_id: dict[str, Option], options: list[Option], snapshot: GameState) -> None:
        if accepted:
            self.commit_id = accepted
            self.commit_source = "jev"
            self.picker.reset()
            return
        held = by_id.get(self.commit_id or "")
        if self.commit_source == "jev" and held is not None and not _finished(held, snapshot):
            return
        if self.commit_source == "jev":
            self.picker.reset()
        chosen = self.picker.choose(options)
        self.commit_id = chosen.id if chosen is not None else None
        self.commit_source = "code"

    def _movement_result(self, snapshot: GameState, perception, options: list[Option], now: float, events: list[dict]) -> Any:
        if self.controller != "jev" or not options or not snapshot_playable(snapshot):
            return self._latest("movement")
        request = movement_request(snapshot, perception, options, now, self.rng)
        if self.sync:
            result = sync_ask(self.client, request)
            self._remember("movement", result)
        elif self.background is not None:
            self.background.submit(request)
        result = self._latest("movement")
        if result is not None and result is not self._logged_move:
            self._logged_move = result
            events.append(_jev_event(result, request_state=request.state if self.sync else None))
        return result

    def _cards(self, snapshot: GameState, now: float, events: list[dict]) -> tuple[str, tuple[str, ...]]:
        screen = _screen(snapshot)
        if screen is None or snapshot.player is None:
            self._card_sig = ""
            return "", ()
        signature = screen.kind + "|" + ",".join(f"{offer.index}:{offer.type}" for offer in screen.offers)
        if signature != self._card_sig:
            self._card_sig = signature
            self._card_result = None
            if self.cards == "jev" and screen.offers and screen.kind != "chest":
                request = card_request(snapshot, screen, now, self.rng)
                if request is not None and self.sync:
                    self._card_result = sync_ask(self.client, request)
                elif request is not None and self.background is not None:
                    self.background.submit(request)
        jev_choice = None
        jev_confidence = None
        card_result = self._card_result if self.sync else self._latest("card")
        if card_result is not None and card_result.ok and _same_cards(card_result, screen):
            jev_choice = card_result.choice
            jev_confidence = card_result.confidence
            if card_result is not self._logged_card:
                self._logged_card = card_result
                events.append(_jev_event(card_result, request_state=None))
        decision = decide_cards(
            screen,
            snapshot.player.weapons,
            snapshot.player.passives,
            snapshot.evolutions,
            use_jev=self.cards == "jev",
            jev_choice=jev_choice,
            jev_confidence=jev_confidence,
        )
        if decision is None:
            return "", ()
        if decision is not None and (decision.name, decision.reason) != getattr(self, "_card_logged", None):
            self._card_logged = (decision.name, decision.reason)
            events.append(
                {
                    "kind": "card",
                    "screen": screen.kind,
                    "pick": decision.name,
                    "reason": decision.reason,
                    "index": decision.index,
                    "offered": [offer.name or offer.type for offer in screen.offers],
                }
            )
        if decision.action == "wait":
            line = "level-up, cards not in the snapshot"
        elif decision.action == "open_close":
            line = "chest: open, then close"
        else:
            line = f"{decision.name} - {decision.reason}"
        keys = decision.keys if self.cards != "off" else ()
        if self.cards == "off" and decision.name:
            line = "suggest " + line
        return line, keys

    def _latest(self, kind: str):
        if self.sync and kind == "card":
            return self._card_result
        if self.background is None:
            return self._card_result if kind == "card" else getattr(self, "_move_result", None)
        return self.background.latest(kind)

    def _remember(self, kind: str, result) -> None:
        if kind == "card":
            self._card_result = result
        else:
            self._move_result = result

    def _idle(self, decider: str) -> MindOutput:
        return MindOutput(Command(), self.controller, decider, "")


def _finished(option: Option, snapshot: GameState) -> bool:
    player = snapshot.player
    if player is None or option.hold:
        return False
    if option.kind != "open":
        return False
    return math.hypot(option.aim_x - player.x, option.aim_y - player.y) < 1.0


def _screen(snapshot: GameState) -> CardScreen | None:
    if snapshot.card_screen is not None:
        return snapshot.card_screen
    if snapshot.run.level_up:
        return CardScreen(kind="level_up")
    return None


def _same_cards(result, screen: CardScreen) -> bool:
    from .cards import _offer_id

    live = {_offer_id(offer) for offer in screen.offers}
    return bool(live) and set(result.option_order) == live


def _jev_event(result, request_state: dict | None) -> dict[str, Any]:
    return {
        "kind": "jev",
        "ok": result.ok,
        "call": result.kind,
        "model": result.model,
        "choice": result.choice,
        "probabilities": result.probabilities,
        "confidence": result.confidence,
        "play_safe": result.play_safe,
        "latency_s": round(result.latency_s, 4),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "option_order": result.option_order,
        "state": result.state,
        "criteria": result.criteria,
        "error": result.error,
    }
