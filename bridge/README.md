# Telemetry bridge

The bridge runs **outside** the game process. The BepInEx plugin publishes `contracts/game-state.v4.schema.json` snapshots to UDP `127.0.0.1:27182` (v3 producers still parse — every v4 field is optional). This package consumes them.

```text
plugin JSON datagram (polar 3x8 enemy/xp/wall + pins + player progress/weapons/blocked)
        ▼
vampirejev.receiver   bind, seq / Hz / drop stats
        ▼
vampirejev.pilot      memory: stuck detector, wall memory, body-flag calibration, mode/heading hysteresis
        ▼
vampirejev.policy     score 8 headings: priced contact, phase dial, openness, kiting, walls, weapon aim, modes
        ▼
vampirejev.gate       armed + VampireSurvivors.exe focused + run playable
        ▼
vampirejev.wasd       8-way SendInput, all-up helper
```

Jev, API keys, retries, and TypeSafe clients belong here later — never in the in-game DLL. Jev should set goals/weights (a *mode*), not WASD.

## Run

```powershell
cd C:\Users\ydste\vampire-survivors-jev\bridge
python -m unittest discover -s tests -v
python -m vampirejev                # automatic modes
python -m vampirejev --mode kite    # lock one mode for an A/B run
```

- Default **SAFE**. **Tap Ctrl** to arm (toggle). `--hold-ctrl` restores hold-to-arm.
- The panel shows **LOOP OFF** until this process is running. Launching the game alone never steers. In Cursor, run `.\run-loop.bat` from the repo root — `.ps1` often opens as text.
- `VSJEV_NUDGE=N` / `S` / `E` / `W` (and diagonals) still forces a heading for A/B tests.
- If you press WASD yourself, the loop disarms and releases keys.
- Pause, level-up, menu, or alt-tab: all keys up within one loop tick.
- Overlay and plugin keep working if this process is not running (UDP is fire-and-forget).

## How the pilot thinks (v1)

The v0 policy fled anything inside the inner ring and treated one bat on a gem pile as a wall. v1 keeps the same 8-way potential field but changes what goes into it:

| Term | What it does | Where it comes from |
|---|---|---|
| **Priced contact** | Inner-ring enemies are projected 0.3 s ahead; each predicted contact costs HP-fraction (`0.02 + 0.10·phase`) divided by your HP ratio. Only *many* contacts (5 early → 2 late), a boss, or a live wall are hard vetoes. | `enemies[].vx/vy`, `hp` |
| **Phase dial** | `phase` rises with `survived_seconds` and `counts.enemies_stage`. Early: XP weight ×1.5, threat ×0.7 → aggressive farming. Late: the reverse. | `run`, `counts` |
| **Hunger** | XP weight ×(1 + 0.5·xp_frac): a near level-up is worth a risk. | `player.xp / xp_next` (v4) |
| **Openness** | Free space in the wedge and its neighbours, counting enemies *and* wall cells. Grows with nearby mass. | `polar.enemy`, `polar.wall` |
| **Kiting** | Above ~6 nearby enemies, headings perpendicular to the blob's centre of mass are rewarded. Stretches the blob into a line and stops "run straight until the wall". | `polar.enemy` |
| **Walls** | Live blocked cardinal → veto (diagonals along it are allowed, slower). Wall bins → strong cost. Remembered/recent walls → soft cost. Hard bounds → cost. | tracker, body flags, `polar.wall`, `bounds` |
| **Weapon aim** | Whip family hits the side you face; knife family fires where you walk. Headings that point them at thin killable mass get a bonus early. Auto/area/orbit weapons add nothing. | `player.weapons[].type`, `facing_x` (v4) |
| **Stickiness** | Bonus for last heading + 150 ms dwell unless vetoed or clearly worse. | pilot state |

**Modes** are weight vectors: `farm` (default), `kite` (≥10 near mass), `flee` (HP < 35 %), `chest` (chest visible, HP ≥ 50 %). They switch with 0.6 s hysteresis (flee is immediate). This is the narrow decision Jev could own later.

**Stuck detection needs no game support.** The tracker compares the keys we hold with the displacement we observe: W held for 0.22 s and `y` unchanged means north is a wall *here*. It vetoes that cardinal for 0.6 s, marks the world cell for 30 s, and remembers "N was a wall recently" for 8 s. Bump N and S once inside the Library corridor and the pilot commits to E/W. With the v4 `polar.wall` channel it never needs to bump at all.

**Body flags** (`player.blocked`, v4) are Phaser's own per-frame collision sides. Left/right are used directly; Phaser's up/down are calibrated against the tracker before use (`yflip=` in the status line shows the verdict). `--no-body-flags` disables them.

## Offline tools

```powershell
python -m vampirejev.sim corridor          # Library-style corridor, v3 fields only
python -m vampirejev.sim corridor --walls  # same with the v4 wall channel
python -m vampirejev.sim pile              # gem pile guarded by two enemies, early game
python -m vampirejev.sim pile --lowhp      # same at 20 % HP
python -m vampirejev.replay ..\recordings\game-state.v3.jsonl --every 2
```

`sim` is a tiny arena (walls slide like Phaser Arcade, enemies chase, gems + magnet, contact damage) that emits the same `GameState` the plugin sends. `tests/test_sim.py` pins the behaviours above. `replay` runs a JSONL recording (`Telemetry.RecordJsonl`) through the pilot and prints modes, vetoes and heading histograms — the player in a recording did not follow the replayed pilot, so its stuck events are approximate.

## Status line

```text
ARMED why=send ... heading=E mode=kite phase=0.31 score=0.82 veto=S,SW blocked=N remembered=- walls_mem=6 stuck_events=3 lv=7 xp=0.62 weapons=WHIP:3,MAGIC_MISSILE:2 body=up yflip=0 wall_cells=9 tilemaps=2 keys=D
```

`why=stuck` means the tracker currently sees a wall and the heading was chosen around it.
