using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace VampireSurvivorsJev.Overlay;

/// <summary>
/// Click-through polar HUD over the game. Uses a per-pixel alpha layered window
/// (no magenta color key — that showed up as hot pink on this Unity build).
/// Exclusive fullscreen can still hide this window — windowed / borderless is required.
/// </summary>
internal sealed class FieldHudForm : Form
{
    private readonly float[] _enemy = new float[PolarPainter.Cells];
    private readonly float[] _xp = new float[PolarPainter.Cells];
    private readonly float[] _wall = new float[PolarPainter.Cells];
    private bool _hasWall;
    private string _blocked = "";
    private bool _inRun;
    private bool _visibleField;
    private bool _hasCam;
    private float _camSx;
    private float _camSy;
    private float _camPw;
    private float _camPh;
    private float _camR0Px;
    private float _camR1Px;
    private float _camR2Px;
    private Bitmap _buffer;

    public FieldHudForm()
    {
        Text = "VampireJev Field";
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        TopMost = true;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.Black;
        DoubleBuffered = false;
    }

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.ExStyle |= 0x00000080 | 0x00080000 | 0x00000020 | 0x08000000;
            return cp;
        }
    }

    public void Apply(
        bool inRun,
        float[] enemy,
        float[] xp,
        float[] radii,
        bool hasCam,
        float camSx,
        float camSy,
        float camPw,
        float camPh,
        float camR0Px,
        float camR1Px,
        float camR2Px,
        float[] wall = null,
        bool hasWall = false,
        string blocked = "")
    {
        _inRun = inRun;
        _hasWall = hasWall && wall != null;
        if (_hasWall)
        {
            Copy(wall, _wall);
        }

        _blocked = blocked ?? "";
        _hasCam = hasCam;
        _camSx = camSx;
        _camSy = camSy;
        _camPw = camPw;
        _camPh = camPh;
        _camR0Px = camR0Px;
        _camR1Px = camR1Px;
        _camR2Px = camR2Px;
        Copy(enemy, _enemy);
        Copy(xp, _xp);
        _ = radii;

        FollowGameWindow();
        if (_visibleField)
        {
            Present();
        }
    }

    public void FollowGameWindow()
    {
        if (!GameWindow.TryGetClientBounds(out var bounds))
        {
            if (_visibleField)
            {
                Hide();
                _visibleField = false;
            }

            return;
        }

        Bounds = bounds;
        SetWindowPos(Handle, new IntPtr(-1), bounds.X, bounds.Y, bounds.Width, bounds.Height, 0x0010);
        if (!_visibleField)
        {
            Show();
            _visibleField = true;
        }
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
    }

    protected override void OnPaint(PaintEventArgs e)
    {
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _buffer?.Dispose();
        _buffer = null;
        base.OnFormClosed(e);
    }

    private void Present()
    {
        var width = Width;
        var height = Height;
        if (width < 64 || height < 64 || !IsHandleCreated)
        {
            return;
        }

        EnsureBuffer(width, height);
        using (var g = Graphics.FromImage(_buffer))
        {
            g.Clear(Color.Transparent);
            if (_inRun)
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.CompositingMode = System.Drawing.Drawing2D.CompositingMode.SourceOver;
                PolarPainter.DrawRings(g, FieldCenter(), FieldRings(), _enemy, _xp, PolarStyle.Field, _hasWall ? _wall : null, _blocked);
            }
        }

        PushLayered(_buffer);
    }

    private PointF FieldCenter()
    {
        if (_hasCam && _camPw > 8f && _camPh > 8f && _camR2Px > 8f)
        {
            return new PointF(_camSx * (Width / _camPw), _camSy * (Height / _camPh));
        }

        return new PointF(Width * 0.5f, Height * 0.5f);
    }

    private float[] FieldRings()
    {
        if (_hasCam && _camPw > 8f && _camPh > 8f && _camR2Px > 8f)
        {
            var scaleX = Width / _camPw;
            return new[]
            {
                0f,
                _camR0Px * scaleX,
                _camR1Px * scaleX,
                _camR2Px * scaleX
            };
        }

        var outer = Math.Min(Width, Height) * 0.42f;
        return new[] { 0f, outer * 0.34f, outer * 0.67f, outer };
    }

    private void EnsureBuffer(int width, int height)
    {
        if (_buffer != null && _buffer.Width == width && _buffer.Height == height)
        {
            return;
        }

        _buffer?.Dispose();
        _buffer = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
    }

    private void PushLayered(Bitmap bitmap)
    {
        var screenDc = GetDC(IntPtr.Zero);
        var memDc = CreateCompatibleDC(screenDc);
        var hBitmap = IntPtr.Zero;
        var oldBitmap = IntPtr.Zero;
        try
        {
            hBitmap = bitmap.GetHbitmap(Color.FromArgb(0));
            oldBitmap = SelectObject(memDc, hBitmap);
            var size = new SIZE { Cx = bitmap.Width, Cy = bitmap.Height };
            var source = new POINT { X = 0, Y = 0 };
            var top = new POINT { X = Left, Y = Top };
            var blend = new BLENDFUNCTION
            {
                BlendOp = 0,
                BlendFlags = 0,
                SourceConstantAlpha = 255,
                AlphaFormat = 1
            };
            UpdateLayeredWindow(Handle, screenDc, ref top, ref size, memDc, ref source, 0, ref blend, 2);
        }
        finally
        {
            if (oldBitmap != IntPtr.Zero)
            {
                SelectObject(memDc, oldBitmap);
            }

            if (hBitmap != IntPtr.Zero)
            {
                DeleteObject(hBitmap);
            }

            DeleteDC(memDc);
            ReleaseDC(IntPtr.Zero, screenDc);
        }
    }

    private static void Copy(float[] source, float[] dest)
    {
        if (source == null)
        {
            return;
        }

        var n = Math.Min(dest.Length, source.Length);
        for (var i = 0; i < n; i++)
        {
            dest[i] = source[i];
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SIZE
    {
        public int Cx;
        public int Cy;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    private struct BLENDFUNCTION
    {
        public byte BlendOp;
        public byte BlendFlags;
        public byte SourceConstantAlpha;
        public byte AlphaFormat;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UpdateLayeredWindow(
        IntPtr hwnd,
        IntPtr hdcDst,
        ref POINT pptDst,
        ref SIZE psize,
        IntPtr hdcSrc,
        ref POINT pptSrc,
        int crKey,
        ref BLENDFUNCTION pblend,
        int dwFlags);

    [DllImport("user32.dll")]
    private static extern IntPtr GetDC(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDc);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateCompatibleDC(IntPtr hDc);

    [DllImport("gdi32.dll")]
    private static extern bool DeleteDC(IntPtr hDc);

    [DllImport("gdi32.dll")]
    private static extern IntPtr SelectObject(IntPtr hDc, IntPtr hObject);

    [DllImport("gdi32.dll")]
    private static extern bool DeleteObject(IntPtr hObject);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint uFlags);
}
