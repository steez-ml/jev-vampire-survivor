using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using VampireSurvivors.Framework;

namespace VampireSurvivorsJev;

/// <summary>
/// 20 Hz harvest from GameManager.Update, then fire-and-forget UDP JSON to 127.0.0.1.
/// Python is the live consumer. Missing receiver must not affect the game.
/// </summary>
internal static class SnapshotPump
{
    internal const int DefaultPort = 27182;
    internal const int DefaultHz = 20;

    private static readonly GameSnapshot Snapshot = new();
    private static readonly StringBuilder Json = new(8192);
    private static readonly IPEndPoint Endpoint = new(IPAddress.Loopback, DefaultPort);
    private static readonly Stopwatch EmitClock = Stopwatch.StartNew();
    private static readonly Stopwatch JsonlClock = Stopwatch.StartNew();
    private static readonly Stopwatch OverlayClock = Stopwatch.StartNew();
    private static readonly Stopwatch HzWindow = Stopwatch.StartNew();

    private static UdpClient _udp;
    private static byte[] _udpBytes = new byte[16384];
    private static long _seq;
    private static int _emitsInWindow;
    private static float _emitHz;
    private static bool _udpFailed;
    private static string _jsonlPath;

    public static void Tick(GameManager gameManager)
    {
        var intervalMs = 1000.0 / Math.Max(1, SnapshotConfig.Hz);
        if (EmitClock.Elapsed.TotalMilliseconds < intervalMs)
        {
            return;
        }

        EmitClock.Restart();
        Emit(gameManager);
    }

    public static void PublishIdle()
    {
        Emit(null);
        OverlayHost.WriteCompact(Snapshot, _emitHz);
    }

    private static void Emit(GameManager gameManager)
    {
        var probeStart = Stopwatch.GetTimestamp();
        PlayerPositionProbe.Fill(gameManager, Snapshot);
        Snapshot.ProbeUs = (Stopwatch.GetTimestamp() - probeStart) * 1_000_000 / Stopwatch.Frequency;
        Snapshot.Seq = ++_seq;
        Snapshot.TMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        _emitsInWindow++;
        if (HzWindow.Elapsed.TotalSeconds >= 1.0)
        {
            _emitHz = (float)(_emitsInWindow / HzWindow.Elapsed.TotalSeconds);
            _emitsInWindow = 0;
            HzWindow.Restart();
        }

        SnapshotJson.Write(Snapshot, Json);
        SendUdp();
        MaybeRecordJsonl();

        if (OverlayClock.Elapsed.TotalMilliseconds >= 100)
        {
            OverlayClock.Restart();
            OverlayHost.WriteCompact(Snapshot, _emitHz);
        }
    }

    private static void SendUdp()
    {
        try
        {
            EnsureUdp();
            var needed = Encoding.UTF8.GetByteCount(Json.ToString());
            if (needed > _udpBytes.Length)
            {
                _udpBytes = new byte[needed];
            }

            var n = Encoding.UTF8.GetBytes(Json.ToString(), 0, Json.Length, _udpBytes, 0);
            _udp.Send(_udpBytes, n, Endpoint);
        }
        catch
        {
            if (!_udpFailed)
            {
                _udpFailed = true;
                DebugSessionLog.Write("P", "SnapshotPump.cs:SendUdp", "UDP send failed once; continuing fire-and-forget");
            }
        }
    }

    private static void EnsureUdp()
    {
        if (_udp != null)
        {
            return;
        }

        var port = SnapshotConfig.Port;
        Endpoint.Port = port;
        _udp = new UdpClient();
        _udp.Client.SendBufferSize = 65507;
        _udp.EnableBroadcast = false;
    }

    private static void MaybeRecordJsonl()
    {
        if (!SnapshotConfig.RecordJsonl)
        {
            return;
        }

        if (JsonlClock.Elapsed.TotalMilliseconds < 100)
        {
            return;
        }

        JsonlClock.Restart();
        try
        {
            if (_jsonlPath == null)
            {
                var dir = Path.Combine(@"C:\Users\ydste\vampire-survivors-jev", "recordings");
                Directory.CreateDirectory(dir);
                _jsonlPath = Path.Combine(dir, "game-state.v3.jsonl");
            }

            File.AppendAllText(_jsonlPath, Json.ToString() + "\n");
        }
        catch
        {
        }
    }
}

internal static class SnapshotConfig
{
    public const float DefaultPolarR0 = 6f;
    public const float DefaultPolarR1 = 16f;
    public const float DefaultPolarR2 = 40f;

    public static int Hz = SnapshotPump.DefaultHz;
    public static int Port = SnapshotPump.DefaultPort;
    public static bool RecordJsonl;
    public static bool ProbeWalls = true;
    public static bool ProbeWeapons = true;
    public static bool ProbeDestructibles = true;
    public static float PolarR0 = DefaultPolarR0;
    public static float PolarR1 = DefaultPolarR1;
    public static float PolarR2 = DefaultPolarR2;

    public static void Bind(BepInEx.Configuration.ConfigFile config)
    {
        Hz = config.Bind("Telemetry", "SnapshotHz", SnapshotPump.DefaultHz, "UDP snapshot emit rate. Start at 20.").Value;
        Port = config.Bind("Telemetry", "UdpPort", SnapshotPump.DefaultPort, "localhost UDP port for v3 JSON snapshots.").Value;
        RecordJsonl = config.Bind(
            "Telemetry",
            "RecordJsonl",
            false,
            "When true, append JSONL at 10 Hz under recordings/. Never the live path.").Value;
        ProbeWalls = config.Bind(
            "Telemetry",
            "ProbeWalls",
            true,
            "Probe the stage collision tilemaps for the polar.wall channel. Set false if a stage misbehaves.").Value;
        ProbeWeapons = config.Bind(
            "Telemetry",
            "ProbeWeapons",
            true,
            "Publish equipped weapon types/levels (player.weapons). Set false to skip the weapon list read.").Value;
        ProbeDestructibles = config.Bind(
            "Telemetry",
            "ProbeDestructibles",
            true,
            "Publish nearby braziers/candelabras (destructibles) as typed pins. Set false to skip that group walk.").Value;
        PolarR0 = config.Bind(
            "Polar",
            "InnerRadius",
            DefaultPolarR0,
            "Fallback inner ring (world units) when the camera is missing. Live radii fit the visible view.").Value;
        PolarR1 = config.Bind(
            "Polar",
            "MidRadius",
            DefaultPolarR1,
            "Fallback mid ring when the camera is missing.").Value;
        PolarR2 = config.Bind(
            "Polar",
            "OuterRadius",
            DefaultPolarR2,
            "Fallback outer ring when the camera is missing. Beyond this still bins into ring 2.").Value;
        if (Hz < 1)
        {
            Hz = 1;
        }

        if (PolarR0 < 0.1f)
        {
            PolarR0 = DefaultPolarR0;
        }

        if (PolarR1 <= PolarR0)
        {
            PolarR1 = PolarR0 + 1f;
        }

        if (PolarR2 <= PolarR1)
        {
            PolarR2 = PolarR1 + 1f;
        }
    }
}
