using HarmonyLib;
using VampireSurvivors.Framework;

namespace VampireSurvivorsJev;

/// <summary>
/// Harmony postfix on the game's existing GameManager.Update.
/// Read-only: no AddComponent, no injected MonoBehaviour. SnapshotPump rate-limits to ~20 Hz.
/// </summary>
[HarmonyPatch(typeof(GameManager), nameof(GameManager.Update))]
internal static class GameManagerUpdatePatch
{
    private static void Postfix(GameManager __instance)
    {
        try
        {
            OverlayHost.PublishFromGame(__instance);
        }
        catch
        {
        }
    }
}
