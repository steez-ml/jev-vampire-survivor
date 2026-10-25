"""Measure Jev from this machine, without the game.

The situations are hand-written in the same shape the navigator sends: words
and buckets, a shuffled choice, and one side question. A run costs cents.
It needs TYPESAFE_API_KEY. With no key it exits and does not call the network.

    python -m vampirejev.probe

Each row is one model, situation, option count, and side-question setting:

- p50_ms / p95_ms: latency of answers that came back;
- late: share of calls that failed or took longer than the arbiter's freshness window;
- agree: share of answers that match the most common pick across shuffles;
- first_slot: share of answers that picked whatever was listed first. Near 1/options is fair;
  well above it means the model leans on position.
"""

from __future__ import annotations

import asyncio
import os
import random
import statistics
import sys
import time
from collections import Counter
from typing import Any

from .arbiter import FRESHNESS_S
from .jevclient import MODEL_PREVIEW, MODEL_STABLE, JevRequest, MissingApiKey, TypeSafeJevClient, require_api_key
from .navigator import MOVEMENT_INSTRUCTIONS

# Long on purpose. A slow answer is a measurement; cutting it off at the navigator's
# timeout would drop exactly the calls the p95 is supposed to show.
PROBE_TIMEOUT_S = 5.0
SEEDS = 5

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
            "brazier_0_1": "Brazier north, medium, a few enemies on the way",
            "mummy_3_1": "A group of mummies southeast, medium; they survive our weapons",
            "chest_5_0": "Treasure chest southwest, far, nothing dangerous on the way",
            "open_6": "Open space west, the emptiest way out",
            "open_4": "Open space south, nothing there",
        },
    },
)


def cases(width: int) -> list[dict]:
    """Every situation that has at least `width` options, cut to its first `width`."""
    picked = []
    for situation in SITUATIONS:
        if len(situation["options"]) < width:
            continue
        options = dict(list(situation["options"].items())[:width])
        picked.append({**situation, "options": options})
    return picked


def request_for(situation: dict, rng: random.Random, side_question: bool) -> JevRequest:
    order = list(situation["options"])
    rng.shuffle(order)
    return JevRequest(
        kind="movement",
        state=situation["state"],
        question_id="next",
        instructions=MOVEMENT_INSTRUCTIONS,
        criteria={item: situation["options"][item] for item in order},
        option_order=order,
        include_play_safe=side_question,
        built_mono=time.monotonic(),
        snapshot_t_ms=0,
        timeout_s=PROBE_TIMEOUT_S,
    )


async def _once(client: Any, situation: dict, rng: random.Random, side_question: bool) -> dict:
    result = await client.ask(request_for(situation, rng, side_question))
    return {
        "name": situation["name"],
        "choice": result.choice,
        "confidence": result.confidence,
        "latency_s": result.latency_s,
        "input_tokens": result.input_tokens,
        "order": list(result.option_order),
        "ok": result.ok,
        "error": result.error,
        "model": result.model,
    }


def summarize_rows(rows: list[dict], freshness_s: float = FRESHNESS_S) -> dict:
    ok = [row for row in rows if row["ok"]]
    out: dict[str, Any] = {"n": len(rows), "ok": len(ok), "error": "" if ok else (rows[0]["error"] if rows else "no rows")}
    if not ok:
        return out
    lat = sorted(row["latency_s"] * 1000.0 for row in ok)
    tokens = [row["input_tokens"] for row in ok if row["input_tokens"] is not None]
    picks = Counter(row["choice"] for row in ok)
    top, top_count = picks.most_common(1)[0]
    out.update(
        p50_ms=lat[len(lat) // 2],
        p95_ms=lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))],
        late=sum(1 for row in rows if not row["ok"] or row["latency_s"] > freshness_s) / len(rows),
        tokens=statistics.mean(tokens) if tokens else None,
        agree=top_count / len(ok),
        first_slot=sum(1 for row in ok if row["order"] and row["choice"] == row["order"][0]) / len(ok),
        top=top,
    )
    return out


def format_row(model: str, situation: str, width: int, side: bool, stats: dict) -> str:
    head = f"{model},{situation},{width},{int(side)},{stats['n']}"
    if not stats["ok"]:
        return f"{head},-,-,-,-,-,-,FAILED {stats['error']}"
    tokens = "-" if stats["tokens"] is None else f"{stats['tokens']:.0f}"
    return (
        f"{head},{stats['p50_ms']:.0f},{stats['p95_ms']:.0f},{stats['late']:.2f},{tokens},"
        f"{stats['agree']:.2f},{stats['first_slot']:.2f},{stats['top']}"
    )


async def run_probe(models: tuple[str, ...] = (MODEL_STABLE, MODEL_PREVIEW), make_client=TypeSafeJevClient, out=print) -> int:
    out("model,situation,options,side,n,p50_ms,p95_ms,late,tokens,agree,first_slot,top_pick")
    for model in models:
        client = make_client(model=model)
        # The first call pays for the TLS handshake. Measure the steady state.
        await _once(client, SITUATIONS[0], random.Random(0), False)
        for width in (3, 8):
            for side in (False, True):
                for situation in cases(width):
                    rows = [await _once(client, situation, random.Random(seed), side) for seed in range(SEEDS)]
                    out(format_row(model, situation["name"], width, side, summarize_rows(rows)))
        close = getattr(client, "aclose", None)
        if close is not None:
            await close()
    out("Write the p50, p95, late, token, agree, and first_slot numbers into docs/ROADMAP.md, then pin the model.")
    return 0


def main(argv: list[str] | None = None) -> int:
    del argv
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("TYPESAFE_API_KEY is not set. The probe does not call Jev until it is.", file=sys.stderr)
        return 2
    try:
        require_api_key()
    except MissingApiKey as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return asyncio.run(run_probe())


if __name__ == "__main__":
    raise SystemExit(main())
