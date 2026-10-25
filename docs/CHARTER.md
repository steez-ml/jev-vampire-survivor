# Charter: Jev plays Vampire Survivors

This is the stable half of the project's guidance. It says what we are building, why, and the principles that do not change as the code does. The changing half (architecture, phases, open questions, decisions) lives in [ROADMAP.md](ROADMAP.md).

Change this file rarely, deliberately, and only with the owner's agreement. If a roadmap idea contradicts something here, stop and discuss it rather than quietly editing either file.

## What this project is

A bot that plays the Steam version of Vampire Survivors, with [Jev](https://docs.typesafe.ai/introduction) as its decision-maker. Jev is TypeSafe's "System One" model. It takes a state plus typed questions and returns typed answers with calibrated probabilities. It does not generate text, and it is fast (about 100 ms per request) and cheap.

The bot is an experiment in using that kind of model well inside a real-time game. Its value is in where Jev is used and where it is not, not just in whether the bot wins.

## The finish line

**One hands-off run that reaches 30:00 on Mad Forest, with any of these four starters:**

| Character | Starting weapon | Why it is in the set |
|---|---|---|
| Antonio | Whip | Hits the side you face |
| Imelda | Magic Wand | Aims itself at the nearest enemy |
| Gennaro | Knife | Fires the way you walk |
| Poe Ratcho | Garlic | Damages whatever touches you |

- In Vampire Survivors, reaching 30:00 clears the stage. The Reaper then appears and ends the run. Reaching 30:00 is the win.
- **Hands-off** means no human input from the moment you arm the bot (tap Ctrl) until 30:00. That includes movement and every level-up, chest, and arcana screen during the run. You still start the run yourself: main menu, stage, and character select.
- **Stretch goal:** a hands-off 30:00 with each of the four starters.

## Philosophy

### 1. Jev decides *what*; code decides *how*

A good player keeps asking "what should I do next?": take that gem pile, walk the whip through that bat line, break that brazier for a chicken, take this card. That is Jev's job.

Everything mechanical is code's job: geometry, distances, counting, timing, dodging, and pressing keys.

In practice, code builds a short list of concrete **options** every moment, each described in words. Jev picks one, and a single code **motor** carries it out. We call this the **navigator** design. [ROADMAP.md](ROADMAP.md) has the details.

### 2. The game never waits for Jev

Jev runs on its own clock, a few times a second. The bot must still make a safe move on every snapshot where Jev has not answered. Every Jev decision has a code fallback, used when the answer is late, unconfident, or missing. Reflexes, meaning "something will hit me in the next fraction of a second", are always code.

### 3. Jev sees words, not numbers

Jev is weak at counting, arithmetic, and reading raw numbers. It is strong at judgments over named facts. Code turns positions and counts into plain statements and buckets ("close", "one heavy enemy on the way", "HP low") before Jev sees them. Jev never gets raw coordinates or occupancy grids.

Small numbers that work as labels, such as the minute, the player level, or a weapon's level, are fine. Jev is never asked to compare, add, or count them.

### 4. Facts come from the game, not from memory

Everything Jev is told comes from the running game, from the game's own data, or from tables we wrote and checked against the game, with the evidence noted next to the table. We never rely on whatever Jev might remember about Vampire Survivors.

The same rule applies to us. Game class and field names are read from this installation's generated assemblies, with evidence recorded, never guessed.

### 5. Narrow questions, combined in code

Each Jev question asks one specific thing. Code combines the answers, applies thresholds, and decides what to do with uncertainty. When a judgment hides several factors, split it into several questions. Do not write one bigger question.

### 6. Jev has to earn its place

Every Jev decision has a code-only counterpart, which is the same fallback from principle 2, and we compare the two on the benchmark. If plain code chooses as well as Jev somewhere, that decision does not need Jev. A Jev feature without that comparison is unfinished.

### 7. Learning lives in our data

Jev's weights are the same for every customer and are not fine-tuned. It will never "learn" that one enemy is tanky and another dies in one hit. That knowledge has to come from the game's data, from what the bot observes during a run, and from logs across runs. We log every Jev question, answer, confidence, and outcome, so any improvement starts from evidence.

### 8. Show the bot's mind

The overlay exists so the owner can see why the bot did what it did. That means the options it saw, what it picked and how confident it was, whether Jev or the fallback decided, and what the motor is doing. If a behavior cannot be explained from the overlay or the logs, the bot is not debuggable yet. Fix that before tuning.

### 9. Measure, then change

Every meaningful change has an offline check (a simulator scenario, a test, or a replay of a recorded run) or a stated reason it can only be tested in the game. Claims about getting better are settled on the benchmark, not by impression.

### 10. Small, understandable steps

The owner is an experienced data engineer who is new to C#, Unity, IL2CPP, and game modding. Explain unfamiliar concepts in plain language before using them. Prefer small changes that can be verified one at a time.

## Boundaries

These are hard rules. Changing one is a charter change.

- **The in-game mod only reads.** No cheats, no gameplay mutations, and no writing to game memory or save files.
- **Jev is never called from inside the game.** Only the external Python bridge talks to Jev.
- **All input goes through the bridge's gates.** Movement keys and menu keys are sent only while the bot is armed, the game window is focused, and the game is in a state where that input belongs. Any human keypress on the movement keys disarms the bot.
- **Credentials stay out of the repo.** The TypeSafe API key lives only in the `TYPESAFE_API_KEY` environment variable. API keys, local game paths, generated game assemblies, and runtime logs are never committed.
- **No network beyond what the design needs:** localhost UDP between the mod and the bridge, and the TypeSafe API from the bridge. The bridge and the overlay talk through local files.

## Non-goals

- **Jev pressing movement keys.** Jev picks options. The motor owns every key press.
- **Screenshots or pixels as the main way to see the game.** The mod reads structured state. Images may be tried later as a side experiment.
- **Reimplementing the game's damage math.** Whether something dies quickly comes from game data and observed outcomes, not from formulas we wrote.
- **Fine-tuning or training models on Jev.** If learning beyond logs is ever added, it is an explicit roadmap decision.
- **Automating menus outside a run** (main menu, character select, results screen), for now.

## Vocabulary

| Term | Meaning here |
|---|---|
| **Jev** | TypeSafe's decision model. State and questions in, typed answers out. |
| **Choice / Score / Noul** | Jev's question types: pick one option from a list, rate something on ordered levels, or give the probability that a statement is true. |
| **Confidence** | How concentrated Jev's probabilities are, from 0 (even split) to 1 (certain). Used to decide whether to act on an answer. |
| **Mod** | The C# plugin inside the game (BepInEx). It reads game state and sends snapshots. It never decides anything. |
| **Snapshot** | One JSON message from the mod describing the game at an instant, sent over localhost UDP about 20 times a second. |
| **Bridge** | The Python program outside the game. It receives snapshots, decides, calls Jev, and sends keys. |
| **Option** | One concrete thing worth doing right now (a target plus a stance), built by code and described in words. Jev picks among options. |
| **Stance** | How to approach an option's target: for example, face it with the whip, hold at the garlic's edge, or keep your distance. |
| **Motor** | The single code controller that carries out the picked option, dodges, and handles walls. The only part that presses movement keys. |
| **Fallback / code picker** | Plain code that picks an option when Jev cannot. It doubles as the "without Jev" comparison. |
| **Card screen** | Any paused in-run screen that needs input: level-up (pick a card), treasure chest (open it, then close it), or arcana (pick one). |
| **Benchmark** | Mad Forest with the four starters above, run hands-off and logged. |
