# Review: PR #1, the navigator

[PR #1](https://github.com/steez-ml/jev-vampire-survivor/pull/1) on branch `navigator` (commit `bebb259`), reviewed 2026-10-24.

## Summary

The PR builds the whole structure of the agreed design, and builds it carefully: perception, options, the code picker, the motor, the Jev client and arbiter, cards, the run log, the overlay's new panel, and snapshot v5. The default is still `baseline`, menu keys are off, and the API key is only read from the environment. That makes it safe to merge as off-by-default code.

It is not ready to be judged against `baseline` yet. The live game still sends no enemy types or HP, so every enemy reaches the navigator as "toughness unknown", and unknown is treated as dangerous. On the old sim scenarios, which use untyped enemies the way the live game does, `code` was frozen in place in front of a guarded gem pile, and it still collects nothing there after the fix. `baseline` collects the pile. Phase 3's "beats baseline" check should wait for Phase 2's enemy reads.

This review fixed thirteen problems on the branch (listed below, each with a check) and leaves eight open. The open ones need either live data or a decision from you.

## What is solid

- The architecture matches the roadmap: Jev picks among options, code acts, and one motor presses keys.
- Jev never sees coordinates or decimals. A test checks every option sentence for decimals.
- The Jev client matches `typesafe-sdk` 0.7.5. I checked the installed package: `AsyncTypeSafeClient(model=, timeout=)`, `system_one(state, questions, model=, retry=, timeout=)`, `RetryPolicy(max_retries=0, timeout=)`, and the response's `.choices`, `.nouls`, and `.usage` all exist with those names.
- The background thread never blocks the 20 Hz loop. Card requests jump the queue.
- The gates are right: pressing WASD on a level-up screen does not disarm, so assisted runs work. The run log never contains the key.
- The mod change is small and isolated: `xp_piles` reuses the gem read that already existed, has its own try/catch and off switch, and its JSON is well-formed both with piles and without.
- The docs say honestly that the code landed ahead of the live checks.

## Fixed on this branch

Each item says what was wrong, why it matters, what changed, and how it is checked.

### 1. The bot froze in front of guarded targets (high)

**What was wrong.** It walked toward a gem pile with an unknown enemy next to it. The reflex stepped back, the next tick the way looked clear again, and it stepped forward. That repeated forever. In the guarded-pile sim the bot stood at the same spot for the whole run. Nothing told the picker the target could not be reached.

**Why it matters.** With today's live data every enemy is unknown, so this would happen at almost every guarded pile, chest, and chicken.

**Fix.** The mind (`mind.py`) watches progress toward the committed target. If the distance has not shrunk by `PROGRESS_STEP` within `NO_PROGRESS_S` (1.5 s), the target is set aside for `SHUN_S` (3 s), and the picker and Jev choose from the rest. Standing next to a target on purpose (arrived, or a hold stance such as garlic's edge) does not count as no progress.

**Check.** The sim scenario `guarded` and the test `test_untyped_guards_on_a_pile_do_not_freeze_the_bot`.

### 2. Route danger was blind past the eight listed enemies (high)

**What was wrong.** Route danger only looked at the up-to-8 enemies the snapshot lists, and the mod only lists enemies inside the inner ring. A far gem pile behind a crowd in the middle ring read as "nothing dangerous on the way", and the code picker would walk into the crowd.

**Fix.** The route check also counts the polar enemy grid in the target's direction, minus enemies we know die fast. The thresholds are `CROWD_LIGHT` = 3 and `CROWD_HEAVY` = 8, and they are uncalibrated. The sentence says what is known, for example "a large group of enemies on the way".

**Check.** The sim scenario `horde` plus two tests: `test_untyped_crowd_in_the_middle_ring_is_not_walked_into` and `test_a_crowd_past_the_listed_bodies_makes_the_way_heavy`. In the sim the bot skips the pile at first, then walks around the crowd to it and takes no damage.

### 3. A Jev pick never expired (high)

**What was wrong.** A Jev commitment lasted until its option disappeared. If Jev started failing or timing out, the bot kept walking to the last accepted target indefinitely, even after the way there filled up.

**Fix.** The pick is kept for at most `HOLD_S` (2 s) after the last accepted answer. It is also dropped if the route's danger has risen since Jev chose it. Both rules are stated in `arbiter.py`, and the roadmap's commitment paragraph now says so.

**Check.** Two tests: `test_a_jev_pick_expires_when_answers_stop` and `test_a_jev_pick_is_dropped_when_the_way_gets_worse`.

### 4. The motor's look-ahead used a number with an unknown unit (medium)

**What was wrong.** The reflex predicts where we will be in 0.3 s using `player.speed`. That is the game's `CharacterController.Speed`, and nobody has confirmed its unit. The baseline pilot deliberately used the walking speed it measured from position changes (`MotionTracker.free_speed`) instead.

**Fix.** The motor uses the measured walking speed, falling back to the baseline's `1.2 × r0` per second until it has a measurement.

**Check.** The existing motor and scenario tests still pass. The real effect needs a live run.

### 5. Perception's HP history could not work as designed (medium; dormant until Phase 2)

**What was wrong:**

- The history held 24 samples, about 1.2 s at 20 Hz. Deciding "this type survives our weapons" needs 1.5 s, so it could never happen.
- An enemy with a type but no ID got an ID made from its position. A moving enemy got a new ID every frame, so the table would grow by roughly 160 entries a second and be rescanned for every enemy on every tick.
- The game reuses enemy objects. A reused ID carried the old enemy's history.

**Fix:**

- History is kept by time (`HISTORY_S` = 3 s) instead of by count.
- IDs not seen for 5 s are forgotten.
- Enemies without a real ID are not tracked.
- A jump back up in HP starts a new history.
- The learned outlook per type is computed once per tick.

**Check.** Three tests: `test_a_type_that_keeps_its_hp_near_us_is_learned_as_surviving`, `test_enemies_without_an_id_are_not_tracked_and_old_ids_are_forgotten`, and `test_a_pooled_id_back_at_full_hp_starts_a_new_history`.

### 6. The danger wording told Jev something nobody knew (medium)

**What was wrong.** Every "light" route read "one enemy on the way that takes a while to kill", including routes with several enemies of unknown toughness. That is a made-up fact in the only text Jev reads.

**Fix.** The sentence comes from what was actually seen:

- "one enemy on the way" or "a few enemies on the way" when toughness is unknown;
- "… that take a while to kill" only for types the data calls sturdy;
- "something that survives our weapons" for tanky enemies and bosses.

**Check.** The test `test_enemies_of_unknown_toughness_are_not_called_slow`.

### 7. Menu keys could double-tap or get stuck (medium; behind `--menu-keys provisional`)

**What was wrong:**

- The tap plan was keyed on the card line's text. If Jev's answer arrived after the rule pick had started tapping, the text changed and a second plan started on the same screen.
- With `--cards jev`, tapping started before Jev had answered.
- Two chests in a row had the same signature, so the second one would never be opened.

**Fix:**

- The mind publishes a screen signature (including card levels) and a `card_ready` flag.
- `card_ready` waits for Jev's card answer, its failure, or the card timeout.
- The executor takes one plan per screen and keeps it.
- The loop resets the executor whenever no card screen is showing.

**Check.** Three tests: `test_a_late_answer_does_not_add_taps_to_the_same_screen`, `test_the_same_screen_again_after_play_gets_its_own_taps`, and `test_jev_cards_wait_for_the_answer_then_fall_back`.

### 8. The fallback share measured the wrong thing (low)

**What was wrong.** Reflex dodges counted as falling back, and `code` runs showed a fallback share even though they never ask Jev.

**Fix.** The share now counts only playable ticks in `jev` runs where code, not Jev, chose the target. Other controllers report none.

**Check.** The test `test_fallback_share_is_only_reported_for_jev`.

### 9. The Phase 0 probe would have under-reported latency (medium)

**What was wrong:**

- The probe used the navigator's 0.8 s timeout, so slow calls failed and dropped out of the p95.
- It counted the first call, which also pays for connection setup.
- It merged the answers from different situations before checking whether shuffling changed the pick, which hides position bias.

**Fix:**

- A 5 s timeout and one discarded warm-up call.
- One row per model, situation, option count, and side-question setting, with:
  - `late`: share failed, or slower than the 1 s freshness window;
  - `agree`: share matching the most common pick across shuffles;
  - `first_slot`: share that picked whatever was listed first. Near 1/options is fair; well above it is position bias.

**Check.** Two tests: `test_late_answers_count_and_position_bias_shows`, and `test_probe_runs_offline_with_the_fake_client`, which runs the whole probe offline with the fake client.

### 10–13. Small things

- **10.** The overlay listed only the first four options, so the picked one could be missing. It is now always shown.
- **11.** The background thread now closes the SDK's HTTP client on shutdown.
- **12.** Removed a dead `if … paused: pass` block from `loop.py`.
- **13.** Gave `_card_logged` a real attribute instead of a `getattr` fallback.

## Still open

### A. No enemy types, HP, or IDs from the game yet (blocker for the Phase 3 benchmark)

Everything the navigator does with "killable", "walk through the bats", or "hold the garlic edge" runs only in sim tests that give enemies types. Live, the stances that allow contact never trigger, the reflex treats every enemy as dangerous, and enemy options are always "keep distance".

**Evidence.** In the guarded-pile sim, `baseline` collects 40 XP and `code` collects 0. Before fix 1 it was frozen; now it gives up and moves on. `baseline` gets the pile because it prices contact. `code` has no stand-in for that until types arrive.

**Recommendation.** Make Phase 2's enemy reads (type, HP, ID, catalog) the next piece of work. Until then:

- use `code` and `jev` only for smoke tests, not benchmarks;
- or decide to add a temporary rule: "at high HP, early in a run, a route with one or two unknown enemies may be walked through". That rule is a policy choice and needs its own sim case, so it is your call.

### B. Distance constants are uncalibrated

The motor and the option builder use world-unit constants guessed without live data:

- contact radius 0.9;
- look-ahead 0.3 s;
- cluster join 3.0;
- route width 2.4;
- keep-distance standoff 3.2;
- option ID cell size 4.0;
- crowd thresholds 3 and 8;
- garlic reach 2.0.

None of these has been compared to the game's actual hit distance.

**Recommendation.** Record one assisted Mad Forest run with `Telemetry.RecordJsonl`. Then read off the enemy distance at the frames where HP drops, and the player radius the snapshot already publishes, and set the constants from those.

### C. The motor has no openness or kiting, and only knows walls it has bumped into

The baseline scored headings for open space, kiting, and the polar wall channel. The new motor walks straight to the target and dodges at the last moment. It reacts to walls only through the stuck detector and wall memory. On the existing corridor scenario it does no worse than the baseline, and Mad Forest is mostly open. It will matter on other stages and in late-game crowds.

**Recommendation.** Revisit after the first live `code` runs, reusing `policy.py`'s openness term in the motor's sidestep choice.

### D. The card screen is not read

Without offers, `--cards` can only say "level-up, cards not in the snapshot". The DOWN/RETURN plan and the cursor's starting position are unverified for 1.16.107 (open questions 3 and 4). Leave `--menu-keys` off until both are confirmed.

### E. Option IDs can drift

A gem pile's ID comes from the 4-unit world cell of its center. When pickups move the center across a cell edge, the ID changes. Enemy groups' IDs move with the group. Either way, Jev's answer names an option that is "gone" and the arbiter rejects it.

**Recommendation.** Before redesigning, measure the rejection rate from the run log (Jev answers whose choice is not in that tick's options).

### F. "Survives" can be learned from enemies our weapons never reached

An enemy that stays near us for 1.5 s without losing HP marks its whole type as surviving, even if it stood behind a whip that faces the other way. This needs Phase 2 data before it can be judged. It may need "near" to mean "inside a weapon's reach" rather than "inside the inner ring".

### G. The reflex checks one point, not the path

It tests where we will be after 0.3 s, not the stretch in between. A fast enemy crossing that stretch is missed. Tune this with B, from live logs.

### H. Keep adding live-like tests

The PR's scenarios all give enemies types and an enemy table, which the live game does not do yet. This review added two untyped scenarios (`horde`, `guarded`). Every new behavior should get one untyped case until Phase 2 lands.

## Suggested order

1. Merge this branch as off-by-default code. `baseline` stays the default.
2. Phase 0: set `TYPESAFE_API_KEY`, run `python -m vampirejev.probe`, and write the numbers into the roadmap.
3. Phase 2 enemy reads (open item A), then the calibration run (B).
4. Only then, the Phase 3 benchmark: `code` vs `baseline`, assisted, same starter.

## How to check this review's changes

```powershell
cd C:\Users\ydste\vampire-survivors-jev\bridge
python -m unittest discover -s tests          # 125 tests, offline
python -m vampirejev.sim guarded              # walks off instead of freezing
python -m vampirejev.sim horde                # skips the pile behind the crowd at first
cd ..
dotnet build                                  # overlay change, 0 warnings
```
