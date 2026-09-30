using System;
using System.IO;

namespace VampireSurvivorsJev;

internal static class DebugSessionLog
{
    private const string LogPath = @"C:\Users\ydste\vampire-survivors-jev\debug-d9ed86.log";

    public static void Write(string hypothesisId, string location, string message, string dataJson = "{}")
    {
        // #region agent log
        try
        {
            var timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var safeMessage = message.Replace("\\", "\\\\").Replace("\"", "\\\"");
            var line =
                "{\"sessionId\":\"d9ed86\",\"runId\":\"hello-world\",\"hypothesisId\":\"" + hypothesisId +
                "\",\"location\":\"" + location +
                "\",\"message\":\"" + safeMessage +
                "\",\"data\":" + dataJson +
                ",\"timestamp\":" + timestamp + "}\n";
            File.AppendAllText(LogPath, line);
        }
        catch
        {
        }
        // #endregion
    }
}
