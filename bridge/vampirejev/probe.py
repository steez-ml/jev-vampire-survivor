"""Measure Jev from this machine, without the game.

The situations are hand-written in the same shape the navigator sends: words
and buckets, a shuffled choice, and one side question. A run costs cents.
It needs TYPESAFE_API_KEY. With no key it exits and does not call the network.

    python -m vampirejev.probe
"""

from __future__ import annotations

import asyncio
import os
import random
import statistics
import sys
import time

from .jevclient import MODEL_PREVIEW, MODEL_STABLE, MissingApiKey, TypeSafeJevClient, require_api_key
from .navigator import JevRequest
from .jevclient import NAV_TIMEOUT_S

SITUATIONS = (
    {
        "name": "early-gems",
        "state": {
            "player": {"hp": "high", "minute": 2, "level": 6, "next_level": "part way"},
            "weapons": ["Whip lv2: hits the side you face"],
            "trend": "enemy count steady, level rising",
            "boss": "none",
        },
        "options": {
            "gems_2_0": "Gem pile east, close, nothing dangerous on the way",
            "bats_3_0": "A few bats east, close; on the whip side; they die fast to our weapons",
            "open_4": "Open space south, nothing there",
        },
    },
    {
        "name": "crowded",
        "state": {
            "player": {"hp": "low", "minute": 8, "level": 21, "next_level": "almost there"},
            "weapons": ["Whip lv4: hits the side you face", "Garlic lv2: damages enemies that touch you"],
            "trend": "enemy count rising, level steady",
            "boss": "nearby",
        },
        "options": {
            "gems_1_2": "Gem pile northeast, medium, something that survives our weapons is on the way",
            "bats_4_0": "A large group of bats east, close; garlic reaches them; they die fast to our weapons",
            "roast_2_1": "Floor chicken west, close, nothing dangerous on the way",
            "brazier_0_1": "Brazier north, medium, one enemy on the way that takes a while to kill",
            "mummy_3_1": "A group of mummies southeast, medium; they survive our weapons",
            "chest_5_0": "Treasure chest southwest, far, nothing dangerous on the way",
            "open_6": "Open space west, the emptiest way out",
            "open_note": "Open space south, nothing there",
        },
    },
)


def cases(width: int) -> list[dict]:
    picked = []
    for situation in SITUATIONS:
        options = dict(list(situation["options"].items())[:width])
        if len(options) < min(width, len(situation["options"])):
            continue
        picked.append({**situation, "options": options})
    return picked


async def _once(client: TypeSafeJevClient, situation: dict, rng: random.Random, side_question: bool) -> dict:
    order = list(situation["options"])
    rng.shuffle(order)
    request = JevRequest(
        kind="movement",
        state=situation["state"],
        question_id="next",
        instructions="Which option would a strong player take next?",
        criteria={item: situation["options"][item] for item in order},
        option_order=order,
        include_play_safe=side_question,
        built_mono=time.monotonic(),
        snapshot_t_ms=0,
        timeout_s=NAV_TIMEOUT_S,
    )
    result = await client.ask(request)
    return {
        "name": situation["name"],
        "choice": result.choice,
        "confidence": result.confidence,
        "latency_s": result.latency_s,
        "input_tokens": result.input_tokens,
        "order": order,
        "ok": result.ok,
        "error": result.error,
        "model": result.model,
    }


async def run_probe() -> int:
    try:
        require_api_key()
    except MissingApiKey as exc:
        print(str(exc), file=sys.stderr)
        print("The probe does not call Jev until TYPESAFE_API_KEY is set.", file=sys.stderr)
        return 2
    print("model,situation,options,side,p50_ms,p95_ms,tokens,choices")
    for model in (MODEL_STABLE, MODEL_PREVIEW):
        client = TypeSafeJevClient(model=model)
        for width in (3, 8):
            for side in (False, True):
                rows = []
                for situation in cases(width):
                    if len(situation["options"]) < width and width == 8:
                        # The early situation has only three options. Skip it at width 8.
                        if len(situation["options"]) < 8:
                            continue
                    for seed in range(5):
                        rows.append(await _once(client, situation, random.Random(seed), side))
                ok = [row for row in rows if row["ok"]]
                if not ok:
                    err = rows[0]["error"] if rows else "no rows"
                    print(f"{model},-,{width},{int(side)},-,-,-,FAILED {err}")
                    continue
                lat = sorted(row["latency_s"] * 1000.0 for row in ok)
                tokens = [row["input_tokens"] for row in ok if row["input_tokens"] is not None]
                choices = sorted({row["choice"] for row in ok})
                p50 = lat[len(lat) // 2]
                p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
                token_text = f"{statistics.mean(tokens):.0f}" if tokens else "-"
                print(f"{model},mixed,{width},{int(side)},{p50:.0f},{p95:.0f},{token_text},{' '.join(choices)}")
        await client.aclose()
    print("Write the p50, p95, token, and shuffle notes into docs/ROADMAP.md, then pin the model.")
    return 0


def main(argv: list[str] | None = None) -> int:
    del argv
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("TYPESAFE_API_KEY is not set. The probe does not call Jev until it is.", file=sys.stderr)
        return 2
    return asyncio.run(run_probe())


if __name__ == "__main__":
    raise SystemExit(main())
