"""Level-up, chest, and arcana decisions.

Code looks first for a card that finishes an evolution we already own half of.
Anything left over is one Jev choice, or, when that answer is missing or unsure,
a short rule: fill an empty weapon slot, else a passive that pairs with a weapon
we own, else the first card. A chest is not a choice. It is opened and closed.

The key names below are a plan, not a claim about this game version. Whether
the bridge actually presses them is a separate switch, because open question 3
(which keys these screens use in 1.16.107) is still unanswered.
"""

from __future__ import annotations

from dataclasses import dataclass

from .arbiter import MIN_CONFIDENCE
from .snapshot import CardOffer, CardScreen, EvolutionPair, PassiveState, WeaponState

WEAPON_SLOTS = 6


@dataclass(frozen=True)
class CardDecision:
    action: str
    reason: str
    index: int = -1
    name: str = ""
    keys: tuple[str, ...] = ()


def decide_cards(
    screen: CardScreen | None,
    weapons: list[WeaponState],
    passives: list[PassiveState],
    evolutions: list[EvolutionPair],
    *,
    use_jev: bool,
    jev_choice: str | None = None,
    jev_confidence: float | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> CardDecision | None:
    if screen is None:
        return None
    if screen.kind == "chest":
        return CardDecision("open_close", "chest has no choice", keys=("RETURN", "RETURN"))
    if not screen.offers:
        return CardDecision("wait", "choice screen has no cards in the snapshot")

    completed = _evolution_card(screen.offers, weapons, passives, evolutions)
    if completed is not None:
        return _choice(completed, "completes an evolution")

    if use_jev and jev_choice and jev_confidence is not None and jev_confidence >= min_confidence:
        match = _by_id(screen.offers, jev_choice)
        if match is not None:
            return _choice(match, "jev")

    fallback = _fallback(screen.offers, weapons, passives, evolutions)
    why = "rules" if not use_jev else "low confidence" if jev_choice else "rules, jev had no answer"
    return _choice(fallback, why)


def card_question(screen: CardScreen, weapons: list[WeaponState], passives: list[PassiveState], evolutions: list[EvolutionPair]) -> tuple[dict, dict[str, str]]:
    """State and criteria for one Choice. Words and labels only."""
    state = {
        "build": [f"{weapon.type} lv{weapon.level}" for weapon in weapons] + [f"{item.type} lv{item.level}" for item in passives],
        "evolutions": [f"{pair.weapon} plus {pair.passive} becomes {pair.result}" for pair in evolutions],
        "screen": screen.kind or "choice",
    }
    criteria = {}
    for offer in screen.offers:
        label = offer.name or offer.type or f"card {offer.index}"
        kind = offer.kind or "card"
        fresh = "new" if offer.is_new else "upgrade"
        text = f"{label}, {kind}, {fresh}"
        if offer.description:
            text = f"{text}. {offer.description}"
        criteria[_offer_id(offer)] = text
    return state, criteria


def _evolution_card(
    offers: list[CardOffer],
    weapons: list[WeaponState],
    passives: list[PassiveState],
    evolutions: list[EvolutionPair],
) -> CardOffer | None:
    owned = {(weapon.type or "").upper() for weapon in weapons}
    owned |= {(item.type or "").upper() for item in passives}
    for pair in evolutions:
        weapon = (pair.weapon or "").upper()
        passive = (pair.passive or "").upper()
        if not weapon or not passive:
            continue
        if weapon in owned and passive not in owned:
            found = _find_type(offers, passive)
            if found is not None:
                return found
        if passive in owned and weapon not in owned:
            found = _find_type(offers, weapon)
            if found is not None:
                return found
    return None


def _fallback(
    offers: list[CardOffer],
    weapons: list[WeaponState],
    passives: list[PassiveState],
    evolutions: list[EvolutionPair],
) -> CardOffer:
    owned_weapons = {(weapon.type or "").upper() for weapon in weapons}
    if len(weapons) < WEAPON_SLOTS:
        for offer in offers:
            if offer.is_new and offer.kind == "weapon":
                return offer
    for offer in offers:
        if offer.kind != "passive":
            continue
        passive = (offer.type or "").upper()
        for pair in evolutions:
            if (pair.passive or "").upper() == passive and (pair.weapon or "").upper() in owned_weapons:
                return offer
    return offers[0]


def _choice(offer: CardOffer, reason: str) -> CardDecision:
    taps = ("DOWN",) * max(0, offer.index) + ("RETURN",)
    return CardDecision("choose", reason, index=offer.index, name=offer.name or offer.type, keys=taps)


def _find_type(offers: list[CardOffer], type_name: str) -> CardOffer | None:
    for offer in offers:
        if (offer.type or "").upper() == type_name or (offer.name or "").upper() == type_name:
            return offer
    return None


def _by_id(offers: list[CardOffer], choice: str) -> CardOffer | None:
    for offer in offers:
        if _offer_id(offer) == choice:
            return offer
    return None


def _offer_id(offer: CardOffer) -> str:
    token = offer.type or offer.name or "card"
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in token)
    return f"card_{offer.index}_{cleaned}"
