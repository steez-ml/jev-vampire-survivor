using BepInEx;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;

namespace VampireSurvivorsJev;

/// <summary>
/// Read-only BepInEx plugin. Unity AddComponent stays disabled.
/// Snapshots go out over localhost UDP; the overlay is a compact sidecar HUD.
/// </summary>
[BepInPlugin("ydste.vampirejev", "Vampire Survivors Jev starter", "0.13.0")]
public sealed class ModEntry : BasePlugin
{
    public override void Load()
    {
        SnapshotConfig.Bind(Config);
        OverlayHost.PublishIdle();
        var overlay = OverlayHost.TryStart();
        try
        {
            var harmony = new Harmony("ydste.vampirejev");
            harmony.PatchAll();
            Log.LogInfo(
                "VampireJev plugin loaded (external overlay=" + overlay +
                ", GameManager.Update patched, udp=127.0.0.1:" + SnapshotConfig.Port +
                " @" + SnapshotConfig.Hz + "Hz)");
            DebugSessionLog.Write(
                "N",
                "ModEntry.cs:Load",
                "Harmony patch applied for v3 polar snapshots",
                "{\"overlay\":\"" + overlay + "\",\"port\":" + SnapshotConfig.Port + "}");
        }
        catch (System.Exception ex)
        {
            Log.LogError("Harmony patch failed: " + ex.GetType().Name + ": " + ex.Message);
            DebugSessionLog.Write(
                "N",
                "ModEntry.cs:Load",
                "Harmony patch failed",
                "{\"error\":\"" + ex.GetType().Name + "\"}");
        }
    }
}
