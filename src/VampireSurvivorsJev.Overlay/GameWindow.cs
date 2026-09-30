using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace VampireSurvivorsJev.Overlay;

/// <summary>
/// Finds the Vampire Survivors game window client area so the field HUD can sit on top.
/// Unity often has a useless MainWindowHandle and an empty title, so we match the
/// process id and keep the largest visible client.
/// </summary>
internal static class GameWindow
{
    public static bool TryGetClientBounds(out Rectangle bounds)
    {
        bounds = Rectangle.Empty;
        var best = Rectangle.Empty;
        var bestArea = 0;
        var pids = new HashSet<uint>();

        foreach (var process in Process.GetProcessesByName("VampireSurvivors"))
        {
            pids.Add((uint)process.Id);
            Consider(process.MainWindowHandle, ref best, ref bestArea);
        }

        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd))
            {
                return true;
            }

            GetWindowThreadProcessId(hwnd, out var pid);
            var title = new StringBuilder(512);
            GetWindowText(hwnd, title, title.Capacity);
            var text = title.ToString();
            if (text.IndexOf("VampireJev", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return true;
            }

            var pidMatch = pids.Contains(pid);
            var titleMatch = text.IndexOf("Vampire Survivors", StringComparison.OrdinalIgnoreCase) >= 0;
            if (!pidMatch && !titleMatch)
            {
                return true;
            }

            Consider(hwnd, ref best, ref bestArea);
            return true;
        }, IntPtr.Zero);

        if (bestArea <= 0)
        {
            return false;
        }

        bounds = best;
        return true;
    }

    private static void Consider(IntPtr hwnd, ref Rectangle best, ref int bestArea)
    {
        if (!TryBoundsFromHwnd(hwnd, out var candidate))
        {
            return;
        }

        var area = candidate.Width * candidate.Height;
        if (area > bestArea)
        {
            bestArea = area;
            best = candidate;
        }
    }

    private static bool TryBoundsFromHwnd(IntPtr hwnd, out Rectangle bounds)
    {
        bounds = Rectangle.Empty;
        if (hwnd == IntPtr.Zero || IsIconic(hwnd) || !IsWindowVisible(hwnd))
        {
            return false;
        }

        if (!GetClientRect(hwnd, out var client) || client.Right <= 32 || client.Bottom <= 32)
        {
            return false;
        }

        var topLeft = new POINT { X = 0, Y = 0 };
        if (!ClientToScreen(hwnd, ref topLeft))
        {
            return false;
        }

        bounds = new Rectangle(topLeft.X, topLeft.Y, client.Right, client.Bottom);
        return true;
    }

    private delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    private static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X;
        public int Y;
    }
}
