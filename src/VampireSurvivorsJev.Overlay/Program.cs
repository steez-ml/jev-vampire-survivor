using System.Globalization;
using System.Drawing.Drawing2D;
using System.IO;

namespace VampireSurvivorsJev.Overlay;

internal static class Program
{
    internal const string StatusPath = @"C:\Users\ydste\vampire-survivors-jev\overlay-status.txt";
    internal const string InputPath = @"C:\Users\ydste\vampire-survivors-jev\overlay-input.txt";

    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new OverlayForm());
    }
}

internal sealed class OverlayForm : Form
{
    private static readonly Color Panel = Color.FromArgb(36, 30, 38);
    private static readonly Color Accent = Color.FromArgb(196, 74, 74);
    private static readonly Color TextMuted = Color.FromArgb(148, 138, 150);
    private static readonly Color Number = Color.FromArgb(236, 208, 156);
    private static readonly Color BarTrack = Color.FromArgb(28, 24, 30);
    private static readonly Color BarFill = Color.FromArgb(196, 74, 74);
    private static readonly Color BarFillOk = Color.FromArgb(176, 122, 74);
    private static readonly Color KeyOff = Color.FromArgb(48, 40, 46);
    private static readonly Color KeyOn = Color.FromArgb(196, 74, 74);

    private readonly FieldHudForm _field = new();
    private readonly System.Windows.Forms.Timer _timer = new();
    private readonly Font _titleFont = new("Segoe UI", 8.5f, FontStyle.Bold);
    private readonly Font _labelFont = new("Segoe UI", 8f);
    private readonly Font _valueFont = new("Consolas", 14f, FontStyle.Bold);
    private readonly Font _smallValueFont = new("Consolas", 11f, FontStyle.Bold);
    private readonly Font _statusFont = new("Segoe UI", 8f, FontStyle.Bold);
    private readonly Font _keyFont = new("Segoe UI", 9f, FontStyle.Bold);

    private Point _dragOffset;
    private bool _dragging;
    private string _state = "waiting";
    private string _x = "—";
    private string _y = "—";
    private string _hp = "—";
    private string _hpMax = "—";
    private string _innerEn = "—";
    private string _xpHot = "—";
    private string _hz = "—";
    private string _keys = "";
    private string _heading = "—";
    private bool _armed;
    private bool _loopLive;
    private bool _focused;
    private float _hpRatio;
    private readonly float[] _polarEnemy = new float[24];
    private readonly float[] _polarXp = new float[24];
    private readonly float[] _polarWall = new float[24];
    private bool _hasWall;
    private string _level = "";
    private string _xpFrac = "";
    private string _weapons = "";
    private string _mode = "";
    private string _blocked = "";
    private readonly float[] _polarRadii = { 6f, 16f, 40f };
    private bool _hasCam;
    private float _camSx;
    private float _camSy;
    private float _camPw;
    private float _camPh;
    private float _camR0Px;
    private float _camR1Px;
    private float _camR2Px;
    private string _why = "";
    private string _gst = "";
    private string _controller = "";
    private string _decider = "";
    private string _confidence = "";
    private string _latency = "";
    private string _fallback = "";
    private string _card = "";
    private string _picked = "";
    private int _mark = -1;
    private readonly string[] _opts = new string[8];

    public OverlayForm()
    {
        Text = "VampireJev";
        TopMost = true;
        ShowInTaskbar = true;
        StartPosition = FormStartPosition.Manual;
        Location = new Point(16, 16);
        ClientSize = new Size(392, 448);
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(18, 16, 22);
        DoubleBuffered = true;

        _field.Show();
        _timer.Interval = 50;
        _timer.Tick += (_, _) => Tick();
        _timer.Start();
        Tick();
        ApplyRoundedRegion();
    }

    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.ExStyle |= 0x08000000;
            return cp;
        }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _field.Close();
        base.OnFormClosed(e);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        ApplyRoundedRegion();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(BackColor);

        using var panelBrush = new SolidBrush(Panel);
        using var accentBrush = new SolidBrush(Accent);
        using var mutedBrush = new SolidBrush(TextMuted);
        using var numberBrush = new SolidBrush(Number);

        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        using (var path = RoundedRect(bounds, 14))
        {
            g.FillPath(panelBrush, path);
        }

        g.FillRectangle(accentBrush, new Rectangle(0, 0, 4, Height));

        g.DrawString("VAMPIREJEV", _titleFont, mutedBrush, 16, 12);
        if (_state != "waiting" && _level.Length > 0)
        {
            var progress = "LV " + _level;
            if (float.TryParse(_xpFrac, NumberStyles.Float, CultureInfo.InvariantCulture, out var frac))
            {
                progress += "  " + Math.Round(frac * 100f).ToString(CultureInfo.InvariantCulture) + "%";
            }

            g.DrawString(progress, _statusFont, numberBrush, 104, 12);
        }

        var statusText = StatusLabel(_state);
        var statusSize = g.MeasureString(statusText, _statusFont);
        var statusRect = new RectangleF(Width - statusSize.Width - 18, 12, statusSize.Width + 10, 18);
        using (var statusBg = new SolidBrush(StatusColor(_state)))
        using (var statusPath = RoundedRect(Rectangle.Round(statusRect), 8))
        {
            g.FillPath(statusBg, statusPath);
        }

        g.DrawString(statusText, _statusFont, _state == "waiting" ? mutedBrush : numberBrush, statusRect.X + 5, 13);

        g.DrawString("X", _labelFont, mutedBrush, 16, 36);
        g.DrawString("Y", _labelFont, mutedBrush, 140, 36);
        g.DrawString(_x, _valueFont, numberBrush, 16, 50);
        g.DrawString(_y, _valueFont, numberBrush, 140, 50);

        g.DrawString("HP", _labelFont, mutedBrush, 16, 78);
        g.DrawString(_hp + " / " + _hpMax, _smallValueFont, numberBrush, 140, 76);
        var bar = new Rectangle(16, 96, 200, 9);
        using (var track = new SolidBrush(BarTrack))
        using (var fill = new SolidBrush(_hpRatio <= 0.35f ? BarFill : BarFillOk))
        using (var barPath = RoundedRect(bar, 4))
        {
            g.FillPath(track, barPath);
            if (_hpRatio > 0f)
            {
                var fillWidth = Math.Max(6, (int)Math.Round((bar.Width - 2) * Math.Min(1f, _hpRatio)));
                var fillRect = new Rectangle(bar.X + 1, bar.Y + 1, fillWidth, bar.Height - 2);
                using var fillPath = RoundedRect(fillRect, 3);
                g.FillPath(fill, fillPath);
            }
        }

        g.DrawString("Hz", _labelFont, mutedBrush, 16, 114);
        g.DrawString(_hz, _smallValueFont, numberBrush, 16, 128);
        g.DrawString("XP", _labelFont, mutedBrush, 80, 114);
        g.DrawString(_xpHot, _smallValueFont, numberBrush, 80, 128);
        g.DrawString("INNER", _labelFont, mutedBrush, 150, 114);
        g.DrawString(_innerEn, _smallValueFont, numberBrush, 150, 128);

        PolarPainter.Draw(
            g,
            new Rectangle(228, 36, 116, 116),
            _polarEnemy,
            _polarXp,
            _polarRadii,
            _state != "waiting",
            _hasWall && _state != "waiting" ? _polarWall : null,
            _state != "waiting" ? _blocked : "",
            _mark);

        var loopText = !_loopLive ? "LOOP OFF" : _armed ? "ARMED" : "LOOP ON";
        if (_loopLive && _armed && string.IsNullOrEmpty(_decider) && !string.IsNullOrEmpty(_mode))
        {
            loopText += "  ·  " + _mode;
        }

        DrawMind(g, mutedBrush, numberBrush, loopText);
        DrawKeys(g, 16, 332);
        g.DrawString(LoopHint(), _labelFont, mutedBrush, 112, 340);
        if (!string.IsNullOrEmpty(_blocked) && _loopLive)
        {
            g.DrawString("wall " + _blocked, _labelFont, mutedBrush, 112, 404);
        }
    }

    private static string ShortWeapons(string csv)
    {
        // "WHIP:3,MAGIC_MISSILE:1" -> "WHIP3 MAGIC_MISSILE1", trimmed to the panel width.
        var parts = csv.Split(',', StringSplitOptions.RemoveEmptyEntries);
        var text = string.Join(" ", parts.Select(p => p.Replace(":", "")));
        return text.Length > 44 ? text.Substring(0, 43) + "…" : text;
    }

    private string LoopHint()
    {
        if (!_loopLive)
        {
            return "run-loop.bat  (keep it open)";
        }

        if (!string.IsNullOrEmpty(_why))
        {
            return _why switch
            {
                "send" => _heading,
                "stuck" => "wall — sliding " + _heading,
                "safe" => "tap Ctrl to arm",
                "unfocused" => "click the game, then tap Ctrl",
                "paused" => "paused — keys released",
                "level-up" => "your upgrade — then it resumes",
                "menu" => "start a run",
                "user-wasd" => "you pressed WASD — tap Ctrl",
                "idle" => "armed, no move yet",
                "no-snapshot" => "waiting for UDP snapshots",
                _ => _why
            };
        }

        if (!_armed)
        {
            return "tap Ctrl to arm";
        }

        return _focused ? _heading : "click the game";
    }

    private void DrawMind(Graphics g, Brush muted, Brush number, string loopText)
    {
        using var line = new Pen(Color.FromArgb(42, 236, 208, 156), 1f);
        g.DrawLine(line, 16, 160, Width - 18, 160);
        g.DrawString(loopText, _statusFont, _loopLive ? number : muted, 16, 168);

        var who = string.IsNullOrEmpty(_decider) ? "" : _decider;
        if (!string.IsNullOrEmpty(who))
        {
            var pill = who.ToUpperInvariant();
            var size = g.MeasureString(pill, _statusFont);
            var rect = new RectangleF(Width - size.Width - 28, 166, size.Width + 12, 18);
            using var bg = new SolidBrush(DeciderColor(who));
            using var path = RoundedRect(Rectangle.Round(rect), 8);
            g.FillPath(bg, path);
            g.DrawString(pill, _statusFont, number, rect.X + 6, 167);
        }

        var meta = _controller;
        if (!string.IsNullOrEmpty(_confidence))
        {
            meta += (meta.Length > 0 ? "    " : "") + "p " + _confidence;
        }

        if (!string.IsNullOrEmpty(_latency))
        {
            meta += "    " + _latency + " ms";
        }

        if (!string.IsNullOrEmpty(_fallback))
        {
            meta += "    fb " + _fallback;
        }

        if (meta.Length > 0)
        {
            g.DrawString(meta, _labelFont, muted, 16, 190);
        }

        var y = 212;
        var shown = 0;
        using var pickBrush = new SolidBrush(Color.FromArgb(236, 208, 156));
        for (var i = 0; i < _opts.Length && shown < 4; i++)
        {
            var row = _opts[i];
            if (string.IsNullOrEmpty(row))
            {
                continue;
            }

            var split = row.IndexOf('|');
            var id = split > 0 ? row.Substring(0, split) : row;
            var facts = split > 0 ? row.Substring(split + 1) : row;
            var picked = id.Length > 0 && id == _picked;
            if (picked)
            {
                g.FillRectangle(pickBrush, 16, y + 3, 3, 11);
            }

            var text = facts.Length > 58 ? facts.Substring(0, 57) + "..." : facts;
            g.DrawString(text, _labelFont, picked ? number : muted, 24, y);
            y += 17;
            shown++;
        }

        if (!string.IsNullOrEmpty(_card))
        {
            var card = _card.Length > 58 ? _card.Substring(0, 57) + "..." : _card;
            g.DrawString(card, _labelFont, number, 16, 284);
        }

        var detail = _state != "waiting" && !string.IsNullOrEmpty(_weapons) ? ShortWeapons(_weapons) : _gst;
        if (!string.IsNullOrEmpty(detail) && _state != "waiting")
        {
            g.DrawString(detail, _labelFont, muted, 16, 306);
        }
    }

    private static Color DeciderColor(string who)
    {
        return who.ToLowerInvariant() switch
        {
            "jev" => Color.FromArgb(90, 176, 140, 72),
            "reflex" => Color.FromArgb(110, 196, 74, 74),
            "code" => Color.FromArgb(70, 120, 110, 100),
            _ => Color.FromArgb(50, 148, 138, 150)
        };
    }

    private void DrawKeys(Graphics g, int x, int y)
    {
        DrawKey(g, x + 28, y, "W", _keys.Contains('W'));
        DrawKey(g, x, y + 26, "A", _keys.Contains('A'));
        DrawKey(g, x + 28, y + 26, "S", _keys.Contains('S'));
        DrawKey(g, x + 56, y + 26, "D", _keys.Contains('D'));
    }

    private void DrawKey(Graphics g, int x, int y, string label, bool on)
    {
        var rect = new Rectangle(x, y, 24, 22);
        using var bg = new SolidBrush(on ? KeyOn : KeyOff);
        using var path = RoundedRect(rect, 4);
        g.FillPath(bg, path);
        var color = on ? Color.FromArgb(236, 208, 156) : Color.FromArgb(120, 110, 118);
        using var brush = new SolidBrush(color);
        var size = g.MeasureString(label, _keyFont);
        g.DrawString(label, _keyFont, brush, x + (24 - size.Width) / 2f, y + 2);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Left)
        {
            _dragging = true;
            _dragOffset = e.Location;
        }

        base.OnMouseDown(e);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        if (_dragging)
        {
            Location = new Point(Location.X + e.X - _dragOffset.X, Location.Y + e.Y - _dragOffset.Y);
        }

        base.OnMouseMove(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        _dragging = false;
        base.OnMouseUp(e);
    }

    protected override void OnDoubleClick(EventArgs e)
    {
        Close();
        base.OnDoubleClick(e);
    }

    private void Tick()
    {
        var armed = _armed;
        var keys = _keys;
        var heading = _heading;
        var panelChanged = ReadStatus();
        ReadInput();
        if (_armed != armed || _keys != keys || _heading != heading)
        {
            panelChanged = true;
        }

        var inRun = _state != "waiting";
        _field.Apply(
            inRun,
            _polarEnemy,
            _polarXp,
            _polarRadii,
            _hasCam,
            _camSx,
            _camSy,
            _camPw,
            _camPh,
            _camR0Px,
            _camR1Px,
            _camR2Px,
            _polarWall,
            _hasWall,
            _loopLive ? _blocked : "",
            _mark);
        Invalidate();
    }

    private bool ReadStatus()
    {
        try
        {
            if (!File.Exists(Program.StatusPath))
            {
                return SetPanel("waiting", "—", "—", "—", "—", "—", "—", "—", 0f);
            }

            string state = "waiting";
            string x = "—";
            string y = "—";
            string hp = "—";
            string hpMax = "—";
            string hz = "—";
            string xpHot = "—";
            string innerEn = "—";
            foreach (var raw in File.ReadAllLines(Program.StatusPath))
            {
                var line = raw.Trim();
                var split = line.IndexOf('=');
                if (split <= 0)
                {
                    continue;
                }

                var key = line.Substring(0, split);
                var value = line.Substring(split + 1);
                switch (key)
                {
                    case "state":
                        state = value;
                        break;
                    case "x" when value.Length > 0:
                        x = value;
                        break;
                    case "y" when value.Length > 0:
                        y = value;
                        break;
                    case "hp" when value.Length > 0:
                        hp = value;
                        break;
                    case "hpMax" when value.Length > 0:
                        hpMax = value;
                        break;
                    case "hz" when value.Length > 0:
                        hz = value;
                        break;
                    case "xp_hot" when value.Length > 0:
                        xpHot = value;
                        break;
                    case "inner_en" when value.Length > 0:
                        innerEn = value;
                        break;
                    case "polar_en":
                        ParseFloats(value, _polarEnemy);
                        break;
                    case "polar_xp":
                        ParseFloats(value, _polarXp);
                        break;
                    case "polar_wall":
                        _hasWall = value.Length > 0;
                        if (_hasWall)
                        {
                            ParseFloats(value, _polarWall);
                        }
                        else
                        {
                            Array.Clear(_polarWall, 0, _polarWall.Length);
                        }
                        break;
                    case "level":
                        _level = value;
                        break;
                    case "xp_frac":
                        _xpFrac = value;
                        break;
                    case "weapons":
                        _weapons = value;
                        break;
                    case "polar_r":
                        ParseFloats(value, _polarRadii);
                        break;
                    case "cam":
                        _hasCam = value == "1";
                        break;
                    case "cam_sx":
                        TryFloat(value, ref _camSx);
                        break;
                    case "cam_sy":
                        TryFloat(value, ref _camSy);
                        break;
                    case "cam_pw":
                        TryFloat(value, ref _camPw);
                        break;
                    case "cam_ph":
                        TryFloat(value, ref _camPh);
                        break;
                    case "cam_r0px":
                        TryFloat(value, ref _camR0Px);
                        break;
                    case "cam_r1px":
                        TryFloat(value, ref _camR1Px);
                        break;
                    case "cam_r2px":
                        TryFloat(value, ref _camR2Px);
                        break;
                    case "gst":
                        _gst = value;
                        break;
                }
            }

            var waiting = state == "waiting";
            if (waiting)
            {
                x = "—";
                y = "—";
                hp = "—";
                hpMax = "—";
                Array.Clear(_polarEnemy, 0, _polarEnemy.Length);
                Array.Clear(_polarXp, 0, _polarXp.Length);
                Array.Clear(_polarWall, 0, _polarWall.Length);
                _hasWall = false;
                _level = "";
                _xpFrac = "";
                _weapons = "";
            }

            var ratio = 0f;
            if (!waiting &&
                float.TryParse(hp, NumberStyles.Float, CultureInfo.InvariantCulture, out var hpValue) &&
                float.TryParse(hpMax, NumberStyles.Float, CultureInfo.InvariantCulture, out var hpMaxValue) &&
                hpMaxValue > 0f)
            {
                ratio = hpValue / hpMaxValue;
            }

            return SetPanel(state, x, y, hp, hpMax, innerEn, xpHot, hz, ratio);
        }
        catch
        {
            return false;
        }
    }

    private void ReadInput()
    {
        try
        {
            if (!File.Exists(Program.InputPath))
            {
                _armed = false;
                _keys = "";
                _heading = "-";
                _loopLive = false;
                _focused = false;
                _why = "";
                _mode = "";
                _blocked = "";
                ClearMind();
                return;
            }

            var age = DateTime.UtcNow - File.GetLastWriteTimeUtc(Program.InputPath);
            _loopLive = age.TotalSeconds < 2.5;
            ClearMind();
            foreach (var raw in File.ReadAllLines(Program.InputPath))
            {
                var line = raw.Trim();
                var split = line.IndexOf('=');
                if (split <= 0)
                {
                    continue;
                }

                var key = line.Substring(0, split);
                var value = line.Substring(split + 1);
                if (key == "armed")
                {
                    _armed = value == "1" || value.Equals("true", StringComparison.OrdinalIgnoreCase);
                }
                else if (key == "keys")
                {
                    _keys = value.ToUpperInvariant();
                }
                else if (key == "heading" && value.Length > 0)
                {
                    _heading = value;
                }
                else if (key == "focused")
                {
                    _focused = value == "1" || value.Equals("true", StringComparison.OrdinalIgnoreCase);
                }
                else if (key == "why")
                {
                    _why = value;
                }
                else if (key == "mode")
                {
                    _mode = value.ToUpperInvariant();
                }
                else if (key == "blocked")
                {
                    _blocked = value.ToUpperInvariant();
                }
                else if (key == "controller")
                {
                    _controller = value;
                }
                else if (key == "decider")
                {
                    _decider = value;
                }
                else if (key == "confidence")
                {
                    _confidence = value;
                }
                else if (key == "latency_ms")
                {
                    _latency = value;
                }
                else if (key == "fallback")
                {
                    _fallback = value;
                }
                else if (key == "card")
                {
                    _card = value;
                }
                else if (key == "option")
                {
                    _picked = value;
                }
                else if (key == "mark")
                {
                    if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out _mark))
                    {
                        _mark = -1;
                    }
                }
                else if (key.Length == 4 && key.StartsWith("opt", StringComparison.Ordinal))
                {
                    if (int.TryParse(key.Substring(3), NumberStyles.Integer, CultureInfo.InvariantCulture, out var slot) && slot >= 0 && slot < _opts.Length)
                    {
                        _opts[slot] = value;
                    }
                }
            }

            if (!_loopLive)
            {
                _armed = false;
                _keys = "";
                _mode = "";
                _blocked = "";
                ClearMind();
            }
        }
        catch
        {
        }
    }

    private void ClearMind()
    {
        _controller = "";
        _decider = "";
        _confidence = "";
        _latency = "";
        _fallback = "";
        _card = "";
        _picked = "";
        _mark = -1;
        Array.Clear(_opts, 0, _opts.Length);
    }

    private static void ParseFloats(string csv, float[] dest)
    {
        var parts = csv.Split(',');
        var n = Math.Min(dest.Length, parts.Length);
        for (var i = 0; i < n; i++)
        {
            if (!float.TryParse(parts[i], NumberStyles.Float, CultureInfo.InvariantCulture, out dest[i]))
            {
                dest[i] = 0f;
            }
        }
    }

    private static void TryFloat(string value, ref float dest)
    {
        if (float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed))
        {
            dest = parsed;
        }
    }

    private static string StatusLabel(string state)
    {
        return state switch
        {
            "running" => "IN RUN",
            "paused" => "PAUSED",
            "level_up" => "YOUR TURN",
            _ => "WAITING"
        };
    }

    private static Color StatusColor(string state)
    {
        return state switch
        {
            "running" => Color.FromArgb(60, 196, 74, 74),
            "paused" => Color.FromArgb(70, 176, 122, 74),
            "level_up" => Color.FromArgb(90, 236, 208, 156),
            _ => Color.FromArgb(40, 148, 138, 150)
        };
    }

    private bool SetPanel(
        string state,
        string x,
        string y,
        string hp,
        string hpMax,
        string innerEn,
        string xpHot,
        string hz,
        float hpRatio)
    {
        if (_state == state && _x == x && _y == y && _hp == hp && _hpMax == hpMax &&
            _innerEn == innerEn && _xpHot == xpHot && _hz == hz &&
            Math.Abs(_hpRatio - hpRatio) < 0.001f)
        {
            return false;
        }

        _state = state;
        _x = x;
        _y = y;
        _hp = hp;
        _hpMax = hpMax;
        _innerEn = innerEn;
        _xpHot = xpHot;
        _hz = hz;
        _hpRatio = hpRatio;
        return true;
    }

    private void ApplyRoundedRegion()
    {
        using var path = RoundedRect(new Rectangle(0, 0, Width, Height), 14);
        Region = new Region(path);
    }

    private static GraphicsPath RoundedRect(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        var d = radius * 2;
        path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
        path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
        path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
        path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }
}
