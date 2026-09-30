# Jev controller — planned

Jev will eventually receive normalized state and answer narrow questions such as:

- which of these candidate movement goals is preferable;
- how urgent is the current danger;
- which offered upgrade best fits the current build;
- should the controller defer because its confidence is low?

The surrounding bridge will own control flow, thresholds, safety rules, and side effects. Jev will not press keys directly and will not run inside the BepInEx plugin.

When this folder becomes executable, use the official TypeSafe Python SDK and keep `TYPESAFE_API_KEY` in the environment, never in source control.
