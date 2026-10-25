# Project guidance

Read these before changing anything:

1. [`docs/CHARTER.md`](docs/CHARTER.md): the goal, the philosophy, the hard boundaries, and the vocabulary. Stable.
2. [`docs/ROADMAP.md`](docs/ROADMAP.md): the current phase, the target architecture, open questions, and the decision log. Living.
3. [`README.md`](README.md): how to build, install, and run what exists today.

If a change would contradict the charter, stop and ask the owner. When a roadmap plan changes, update the roadmap and add a decision-log entry.

## Working with the owner

The owner is an experienced data engineer who is new to C#, Unity, IL2CPP, and game modding. Explain unfamiliar concepts in plain language before using them. Prefer small changes that can be verified one at a time.

## Hard rules

- The in-game mod only reads. No cheats, no gameplay mutations, and no writing to game memory or saves.
- Jev is called only from the Python bridge, never from the in-game DLL. The API key comes from `TYPESAFE_API_KEY` only.
- Movement and menu keys go only through the bridge's gates: armed, game window focused, and a game state where that input belongs. Human WASD disarms.
- No network beyond localhost UDP (mod to bridge) and the TypeSafe API (bridge only).
- Never commit API keys, local game paths, generated assemblies, or runtime logs.
- Jev gets words and buckets, never raw coordinates or grids. Arithmetic, geometry, and counting stay in code.

## Game and loader lessons (learned the hard way)

- Load through BepInEx 6 IL2CPP (`winhttp.dll`). Keep MelonLoader's `version.dll` disabled: it crashes this Unity 6 install in `coreclr.dll`.
- `UnityLogListening = false` in `BepInEx.cfg`.
- Never retry Unity `AddComponent` or `ClassInjector`. They crash this install. That is why the overlay is a separate process.
- Do not invent Vampire Survivors class or field names. Inspect this installation's `BepInEx\interop` assemblies first, and record the evidence in the `PlayerPositionProbe` doc comment.
- Every new game read is isolated in its own try/catch, logs once to `debug-*.log`, and disables itself for the session. Heavy probes get a config switch.
- Snapshot schema changes are additive, and new fields are optional. Keep game-specific adapters separate from the normalized contracts in `contracts/`.

## Checks

Every meaningful change has an offline check or a stated reason it can only be tested in the game:

- Decision logic gets a `bridge/vampirejev/sim.py` scenario or a test in `bridge/tests/`.
- Recordings can be replayed with `python -m vampirejev.replay`.
- New game reads get an evidence line in the `PlayerPositionProbe` doc comment.
- Jev integrations are tested against a fake client offline. Claims that Jev helps are settled on the roadmap's benchmark protocol.
