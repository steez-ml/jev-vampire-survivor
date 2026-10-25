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

from .arbiter import DANGER_RANK, HOLD_S, accept_choice, fresh_play_safe
from .cards import decide_cards
from .gate import snapshot_playable
from .jevclient import CARD_TIMEOUT_S, PINNED_MODEL, TypeSafeJevClient
from .motor import ARRIVE, Motor
from .navigator import JevBackground, card_request, movement_request, sync_ask
from .options import Option, build_options
from .perception import PerceptionMemory, perceive
from .picker import CodePicker
from .policy import Command
from .polar import SECTOR_NAMES
from .snapshot import CardScreen, GameState

# A target we have stopped closing on is set aside for a while, so the motor does
# not dither forever in front of a guard it will not touch. Distances are world
# units and uncalibrated.
NO_PROGRESS_S = 1.5
PROGRESS_STEP = 0.3
SHUN_S = 3.0


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
    # Share of playable ticks where code, not Jev, chose the target. None unless the controller is jev.
    fallback_share: Optional[float] = None
    reflex: bool = False
    mark_sector: int = -1
    blocked: frozenset[str] = frozenset()
    remembered: frozenset[str] = frozenset()
    stuck: bool = False
    body_y_flipped: Optional[bool] = None
    card_line: str = ""
    card_keys: tuple[str, ...] = ()
    # Same screen, same signature. card_ready is False while a Jev card answer may still change the pick.
    card_signature: str = ""
    card_ready: bool = False
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
        self._jev_at = 0.0
        self._jev_danger = "clear"
        self._progress: tuple[str, float, float] | None = None
        self._shunned: dict[str, float] = {}
        self._ticks = 0
        self._fallback = 0
        self._logged_move: Any = None
        self._logged_card: Any = None
        self._card_logged: tuple[str, str] | None = None
        self._card_sig = ""
        self._card_since = 0.0
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
        self._shunned = {ident: until for ident, until in self._shunned.items() if until > now}
        options = [item for item in options if item.id not in self._shunned]
        by_id = {item.id: item for item in options}

        movement = self._movement_result(snapshot, perception, options, now, events)
        play_safe = fresh_play_safe(movement, now)
        accepted = accept_choice(movement, set(by_id), now) if self.controller == "jev" else None
        self._commit(accepted, by_id, options, snapshot, now)
        chosen = by_id.get(self.commit_id or "")
        steer = self.motor.step(snapshot, chosen if snapshot_playable(snapshot) else None, perception, sent_keys, play_safe)
        if snapshot_playable(snapshot):
            self._watch_progress(chosen, snapshot, now)

        if steer.note == "nudge":
            decider = "nudge"
        elif steer.reflex:
            decider = "reflex"
        elif self.controller == "jev" and self.commit_source == "jev" and chosen is not None:
            decider = "jev"
        else:
            decider = "code"

        if self.controller == "jev" and snapshot_playable(snapshot):
            self._ticks += 1
            if self.commit_source != "jev" or chosen is None:
                self._fallback += 1

        card_line, card_keys, card_signature, card_ready = self._cards(snapshot, now, events)
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
            fallback_share=(self._fallback / self._ticks) if self._ticks else None,
            reflex=steer.reflex,
            mark_sector=mark,
            blocked=steer.blocked,
            remembered=steer.remembered,
            stuck=steer.stuck,
            body_y_flipped=steer.body_y_flipped,
            card_line=card_line,
            card_keys=card_keys,
            card_signature=card_signature,
            card_ready=card_ready,
            model=model,
            events=events,
        )

    def _commit(self, accepted: str | None, by_id: dict[str, Option], options: list[Option], snapshot: GameState, now: float) -> None:
        if accepted:
            self.commit_id = accepted
            self.commit_source = "jev"
            self._jev_at = now
            self._jev_danger = by_id[accepted].danger
            self.picker.reset()
            return
        held = by_id.get(self.commit_id or "")
        if (
            self.commit_source == "jev"
            and held is not None
            and not _finished(held, snapshot)
            and now - self._jev_at <= HOLD_S
            and DANGER_RANK.get(held.danger, 2) <= DANGER_RANK.get(self._jev_danger, 2)
        ):
            return
        if self.commit_source == "jev":
            self.picker.reset()
        chosen = self.picker.choose(options)
        self.commit_id = chosen.id if chosen is not None else None
        self.commit_source = "code"

    def _watch_progress(self, chosen: Option | None, snapshot: GameState, now: float) -> None:
        player = snapshot.player
        if chosen is None or player is None or chosen.hold or chosen.kind == "open":
            self._progress = None
            return
        dist = math.hypot(chosen.aim_x - player.x, chosen.aim_y - player.y)
        arrived = dist < 2.0 * ARRIVE
        if arrived or self._progress is None or self._progress[0] != chosen.id or dist < self._progress[1] - PROGRESS_STEP:
            self._progress = (chosen.id, dist, now)
            return
        if now - self._progress[2] >= NO_PROGRESS_S:
            self._shunned[chosen.id] = now + SHUN_S
            self._progress = None

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

    def _cards(self, snapshot: GameState, now: float, events: list[dict]) -> tuple[str, tuple[str, ...], str, bool]:
        screen = _screen(snapshot)
        if screen is None or snapshot.player is None:
            self._card_sig = ""
            return "", (), "", False
        signature = screen.kind + "|" + ",".join(f"{offer.index}:{offer.type}:{offer.level}" for offer in screen.offers)
        if signature != self._card_sig:
            self._card_sig = signature
            self._card_since = now
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
        answered = card_result is not None and _same_cards(card_result, screen) and card_result.built_mono >= self._card_since
        if answered and card_result.ok:
            jev_choice = card_result.choice
            jev_confidence = card_result.confidence
        if answered and card_result is not self._logged_card:
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
            return "", (), signature, False
        ready = decision.action == "open_close" or (
            decision.action == "choose"
            and (
                self.cards != "jev"
                or decision.reason in {"completes an evolution", "jev"}
                or answered
                or self.client is None
                or (self.background is not None and self.background.disabled)
                or now - self._card_since >= CARD_TIMEOUT_S
            )
        )
        if (decision.name, decision.reason) != self._card_logged:
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
        return line, keys, signature, ready and bool(keys)

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
