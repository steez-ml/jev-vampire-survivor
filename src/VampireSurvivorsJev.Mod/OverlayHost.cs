using System.Diagnostics;
using System.Globalization;
using System.IO;
using VampireSurvivors.Framework;

namespace VampireSurvivorsJev;

/// <summary>
/// Sidecar overlay: compact HUD file (~10 Hz) plus a separate WinForms process.
/// The overlay does not parse the full 32-enemy UDP JSON.
/// </summary>
internal static class OverlayHost
{
    internal const string StatusPath = @"C:\Users\ydste\vampire-survivors-jev\overlay-status.txt";

    private const string OverlayExe =
        @"C:\Users\ydste\vampire-survivors-jev\artifacts\Debug\net6.0-windows\VampireSurvivorsJev.Overlay.exe";

    private static string _lastPayload;

    public static void PublishIdle()
    {
        SnapshotPump.PublishIdle();
    }

    public static void PublishFromGame(GameManager gameManager)
    {
        SnapshotPump.Tick(gameManager);
    }

    public static string TryStart()
    {
        foreach (var process in Process.GetProcessesByName("VampireSurvivorsJev.Overlay"))
        {
            try
            {
                process.Kill();
            }
            catch
            {
            }
        }

        if (!File.Exists(OverlayExe))
        {
            return "missing-exe";
        }

        Process.Start(new ProcessStartInfo(OverlayExe)
        {
            UseShellExecute = true
        });
        return "started";
    }

    public static void WriteCompact(GameSnapshot snapshot, float emitHz)
    {
        var inv = CultureInfo.InvariantCulture;
        string state;
        if (!snapshot.Running)
        {
            state = "waiting";
        }
        else if (snapshot.LevelUp)
        {
            state = "level_up";
        }
        else if (snapshot.Paused)
        {
            state = "paused";
        }
        else
        {
            state = "running";
        }

        var x = snapshot.HasPlayer ? snapshot.PlayerX.ToString("0.00", inv) : "";
        var y = snapshot.HasPlayer ? snapshot.PlayerY.ToString("0.00", inv) : "";
        var hp = snapshot.HasPlayer ? snapshot.Hp.ToString("0.#", inv) : "";
        var hpMax = snapshot.HasPlayer ? snapshot.HpMax.ToString("0.#", inv) : "";

        var xpHot = PolarGrid.HottestXpSector(snapshot.PolarXp);
        var innerEn = PolarGrid.InnerEnemyMass(snapshot.PolarEnemy).ToString("0", inv);
        var level = snapshot.HasProgress ? snapshot.Level.ToString(inv) : "";
        var xpFrac = snapshot.HasProgress && snapshot.XpNext > 0.01f
            ? Math.Clamp(snapshot.Xp / snapshot.XpNext, 0f, 1f).ToString("0.00", inv)
            : "";
        var weapons = "";
        for (var i = 0; i < snapshot.WeaponCount; i++)
        {
            if (i > 0)
            {
                weapons += ",";
            }

            weapons += snapshot.Weapons[i].TypeName + ":" + snapshot.Weapons[i].Level.ToString(inv);
        }

        var text =
            "hello=Hello world\n" +
            "state=" + state + "\n" +
            "x=" + x + "\n" +
            "y=" + y + "\n" +
            "hp=" + hp + "\n" +
            "hpMax=" + hpMax + "\n" +
            "inner_en=" + innerEn + "\n" +
            "xp_hot=" + xpHot + "\n" +
            "polar_en=" + JoinFloats(snapshot.PolarEnemy, inv) + "\n" +
            "polar_xp=" + JoinFloats(snapshot.PolarXp, inv) + "\n" +
            "polar_wall=" + (snapshot.HasWall ? JoinFloats(snapshot.PolarWall, inv) : "") + "\n" +
            "level=" + level + "\n" +
            "xp_frac=" + xpFrac + "\n" +
            "weapons=" + weapons + "\n" +
            "polar_r=" + snapshot.PolarR0.ToString("0.#", inv) + "," +
            snapshot.PolarR1.ToString("0.#", inv) + "," +
            snapshot.PolarR2.ToString("0.#", inv) + "\n" +
            "cam=" + (snapshot.HasCamera ? "1" : "0") + "\n" +
            "cam_sx=" + snapshot.CamSx.ToString("0.#", inv) + "\n" +
            "cam_sy=" + snapshot.CamSy.ToString("0.#", inv) + "\n" +
            "cam_pw=" + snapshot.CamPw.ToString("0.#", inv) + "\n" +
            "cam_ph=" + snapshot.CamPh.ToString("0.#", inv) + "\n" +
            "cam_r0px=" + snapshot.CamR0Px.ToString("0.#", inv) + "\n" +
            "cam_r1px=" + snapshot.CamR1Px.ToString("0.#", inv) + "\n" +
            "cam_r2px=" + snapshot.CamR2Px.ToString("0.#", inv) + "\n" +
            "paused=" + (snapshot.Paused ? "1" : "0") + "\n" +
            "level_up=" + (snapshot.LevelUp ? "1" : "0") + "\n" +
            "gst=" + (snapshot.GameStateName ?? "").Replace("\n", " ").Replace("\r", "") + "\n" +
            "seq=" + snapshot.Seq.ToString(inv) + "\n" +
            "hz=" + emitHz.ToString("0.0", inv) + "\n" +
            "probe_us=" + snapshot.ProbeUs.ToString(inv) + "\n";

        if (text == _lastPayload)
        {
            return;
        }

        _lastPayload = text;
        var tempPath = StatusPath + ".tmp";
        File.WriteAllText(tempPath, text);
        File.Copy(tempPath, StatusPath, true);
    }

    private static string JoinFloats(float[] values, CultureInfo inv)
    {
        var parts = new string[values.Length];
        for (var i = 0; i < values.Length; i++)
        {
            parts[i] = values[i].ToString("0.##", inv);
        }

        return string.Join(",", parts);
    }
}
