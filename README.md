# Vampire Survivors + Jev AI

This repository is a beginner-friendly path toward an AI agent that can play Steam Vampire Survivors. The owner is a data engineer new to C#, Unity, and IL2CPP.

**Current phase: v1 polar pilot.** The in-game DLL is still read-only. It publishes a 3×8 occupancy grid (enemies, XP, and now **walls**), inner-ring enemies with velocity, bosses, chests, and the player's level/XP/magnet/facing/equipped weapons/collision flags. A Python pilot scores eight WASD headings with *priced* contact (walk through one bat for a pile early; do not late), an openness/kiting term so it stops running into corridor walls, a stuck detector plus wall memory, and a small weapon-aim term (whip faces, knife walks). You still pick upgrades. Jev is not in this phase.

## Observed install (this machine)

These values were read from the local Steam copy, not guessed:

- Game directory: `C:\Program Files (x86)\Steam\steamapps\common\Vampire Survivors`
- Steam AppID: `1794680`
- Game: Vampire Survivors **1.16.107** by **poncle**
- Engine: Unity **6000.0.62f1**, **IL2CPP** (`GameAssembly.dll`)
- Build SDK: .NET **6.0.428**
- Loader: **BepInEx 6 IL2CPP** (Thunderstore pack 6.0.755) via Doorstop `winhttp.dll`

**IL2CPP, in one sentence:** Unity compiled the game’s C# into native C++. BepInEx generates C# *proxy* assemblies under `BepInEx\interop` on first launch so a plugin can still name game types.

**Do not use MelonLoader on this install.** MelonLoader’s `version.dll` crashes Unity 6 here in `coreclr.dll` (0xc0000005 / HRESULT `80131506`). Keep it disabled as `version.dll.melonloader.bak`. Unity `AddComponent` / `ClassInjector` hits the same crash — do not retry it.

## The mental model

```text
Steam Vampire Survivors.exe
        │ Doorstop winhttp.dll
        ▼
BepInEx 6 IL2CPP plugin (VampireSurvivorsJev.dll)
        │ Harmony postfix on GameManager.Update (read-only)
        ├─ compact overlay-status.txt  (~10 Hz HUD)
        └─ UDP 127.0.0.1:27182 JSON    (~20 Hz, fire-and-forget, v4)
                │
                ▼
Python pilot (bridge/vampirejev)
        │ memory: stuck detector, wall memory, mode hysteresis
        │ scoring: priced contact, phase, openness, kiting, walls, weapon aim
        ▼
gated WASD via SendInput
```

The plugin stays inside the game process and does not call Jev, hold API keys, or inject Rewired. Python is the only live consumer of the full snapshot. If Python is not running, UDP send still succeeds; the overlay still works.

## What is already here

| Area | Purpose now | Purpose later |
|---|---|---|
| `src/VampireSurvivorsJev.Mod` | BepInEx plugin: harvest + UDP + overlay file | More evidenced fields |
| `src/VampireSurvivorsJev.Overlay` | Compact HUD process (panel + on-game field HUD with wall cells) | Same |
| `contracts/game-state.v4.schema.json` | Live snapshot: polar 3×8 enemy/xp/wall + pins + player progress (`source: bepinex`) | Shared with Jev |
| `bridge/vampirejev` | Receiver, pilot (memory), policy (scoring), WASD, gates, sim, replay | Jev picks the mode |
| `jev` | Design notes only | TypeSafe calls from the bridge |

`contracts/game-state.v1.schema.json` and `v2` are leftovers (MelonLoader attempt, then k-nearest gems). `v3` is what the plugin sent before walls/weapons; **v4** is additive (every new field optional) and is the control plane now.

## Setup on Windows

### 1. Build tools

```powershell
dotnet --list-sdks
```

You need a `6.0.x` SDK. This machine has `6.0.428`.

### 2. BepInEx baseline (already proven on this install)

1. Close Vampire Survivors.
2. BepInEx 6 IL2CPP-win-x64 lives next to `VampireSurvivors.exe` (`winhttp.dll` + `BepInEx\`).
3. `BepInEx\config\BepInEx.cfg` must keep `UnityLogListening = false`. Empty BepInEx crashed until that was set.
4. Confirm MelonLoader’s proxy is **not** loaded: no `version.dll`, only `version.dll.melonloader.bak` if you still have the files.
5. First BepInEx launch generates `BepInEx\interop\VampireSurvivors.Runtime.dll`. Inspect that file before adding game types.

### 3. Build the plugin and overlay

From the repository root:

```powershell
dotnet build .\VampireSurvivorsJev.sln -c Debug
```

Copy the plugin (the csproj leaves this manual so we do not write the Steam folder by surprise):

```powershell
Copy-Item .\artifacts\Debug\net6.0\VampireSurvivorsJev.dll `
  "C:\Program Files (x86)\Steam\steamapps\common\Vampire Survivors\BepInEx\plugins\VampireSurvivorsJev.dll" `
  -Force
```

The overlay exe is `artifacts\Debug\net6.0-windows\VampireSurvivorsJev.Overlay.exe`. The plugin starts it. The small panel shows HP, XP hot sector, and the current WASD keys. A separate click-through field HUD sits on the game window: the character is the center of a 3×8 polar grid scaled to the camera view (red = enemies, gold = XP). This cannot draw on exclusive fullscreen — use **Windowed** or **Borderless** in the game's video settings. Steam launch is fine.

### 4. Python loop (required for steering)

No extra packages. Cursor often opens `.ps1` as a text file, so use the `.bat`:

```powershell
.\run-loop.bat
```

Or from `bridge/`:

```powershell
cd .\bridge
python -m unittest discover -s tests -v
python -m vampirejev
```

Keep that terminal open. The panel should switch from **LOOP OFF** to **LOOP ON**. Click the Vampire Survivors window, then **tap Ctrl once** to arm (tap again to disarm). Default is SAFE. While armed the panel shows the pilot **mode** (`FARM` / `KITE` / `FLEE` / `CHEST`) next to ARMED and `wall N` when the stuck detector sees a wall; the field HUD tints wall cells grey and marks blocked sides in red. `VSJEV_NUDGE=N` still forces north, and `.\run-loop.bat --mode kite` locks one mode for A/B runs. Pressing WASD yourself disarms and releases keys. Pause, level-up, alt-tab, or a menu snapshot also releases keys. `bridge/README.md` explains each scoring term.

**The bot does not start with Steam.** Two processes:

1. Launch Vampire Survivors (plugin + overlay panel + field HUD).
2. Run `.\run-loop.bat` and keep it open. Click the game, tap Ctrl.

UDP port is `27182` (`VSJEV_UDP_PORT` / BepInEx `Telemetry.UdpPort`). Optional JSONL recording is a BepInEx config flag (`Telemetry.RecordJsonl`), 10 Hz, never the live path.

## Snapshot (v4)

Each datagram is one JSON object: `seq`, `t_ms`, `source: bepinex`, run flags, optional player/bounds, a **3×8 polar grid** (enemy count, XP `Pickup.Value`, and — when the stage has a tileset — `wall` hit fractions from `PhaserTilemap.IsTileAtPosition`), inner-ring enemies (cap 8), bosses (`EnemyController.IsBoss`), chests, stage vs published counts (+ `tilemaps`), and `perf.probe_us`.

v4 player extras, all optional: `level`, `xp`, `xp_next` (`LevelUpFactory.XpRequiredToLevelUp`), `magnet` (`MagnetZone.Radius`), `facing_x`, `move_dir`, `blocked` (Phaser `body._blocked` sides, raw names), `weapons[] {type, level, evo}` (`WeaponType` enum names from `WeaponsManager.ActiveEquipment`).

Sector 0 is **+Y (north / W key)**, then clockwise. Gems are not sent as k-nearest coordinates; they only fill XP bins. Inactive pooled objects are skipped. Each new v4 read is isolated: a failing getter logs once to `debug-*.log` and disables only itself. `Telemetry.ProbeWalls` / `Telemetry.ProbeWeapons` in `BepInEx\config\ydste.vampirejev.cfg` switch the two heavier probes off.

## QA (offline, agent)

- `dotnet build .\VampireSurvivorsJev.sln -c Debug`
- `cd bridge; python -m unittest discover -s tests -v` (schema, polar, policy, memory, weapons, gate, wasd, and arena scenarios)
- Example JSON validates against `contracts/game-state.v3.schema.json` and `v4`
- `python -m vampirejev.sim corridor` / `pile` print a trajectory; `python -m vampirejev.replay <jsonl>` re-runs a recording

## QA (you, Steam launch — one concern per run)

1. Overlay **XP HOT** moves when you walk past a gem pile; the on-game wedges tint gold toward the pile (character still yours until armed).
2. **Inlaid Library** (walls): grey wedges appear on the field HUD toward the shelves above/below; the panel's `wall_cells` in the loop status line is > 0 and `tilemaps` ≥ 1. If the grey never appears, `Stage.HasTileSet` was false or the probe disabled itself — check `debug-*.log`.
3. Arm in the Library with a blob to the south: the pilot should run E or W along the corridor, not pin against the north shelf. If it does pin, the status line should show `blocked=N` within a quarter second and the heading change.
4. Early game, full HP, small gem pile under one or two enemies: it should walk in and take it (`mode=farm`). Same pile at < 35 % HP: `mode=flee`, it leaves it. A lone gem with no enemies nearby should still be walked to.
5. Low HP on Mad Forest: a chicken (`ROAST`) or a clear brazier should pull the character; a chicken sitting in a blob should not. Status line shows `pickups=ROAST` / `loot=BRAZIER`.
6. `body=` shows raw Phaser sides when pushing a wall; after a couple of bumps `yflip=` appears (0 = Phaser up is world north).
7. Panel shows `LV n  xx%` and the weapon list; `weapons=` in the status line names your build.
8. `VSJEV_NUDGE=N` still forces north; `--mode kite` keeps the mode fixed.
9. Python `recv_hz` stays **≥20**; note `probe_us` (the wall probe adds ~80 tile lookups per snapshot). If it jumps a lot, set `Telemetry.ProbeWalls = false`.

If any v4 read crashes the game (not just logs), set the matching `Telemetry.Probe*` flag to false or revert that read (same rule as `AddComponent`).

## Important boundaries

- No TypeSafe API key in this repository or the game folder.
- No Jev calls from the in-game DLL.
- No Rewired injection and no writing `CurrentPos`.
- Do not invent Vampire Survivors class names. Inspect `BepInEx\interop` first (the evidence list lives in the `PlayerPositionProbe` doc comment).
- Policy is a small 8-way potential field with memory. No Jev, no Rewired, no writing `CurrentPos`.

## References

- BepInEx: <https://github.com/BepInEx/BepInEx>
- Vampire Survivors modding reference: <https://github.com/lukeod/vampiresurvivors-modding>
- TypeSafe Jev introduction: <https://docs.typesafe.ai/introduction>
