using System.Drawing.Drawing2D;

namespace VampireSurvivorsJev.Overlay;

internal readonly struct PolarStyle
{
    public readonly bool FillOccupied;
    public readonly bool FillEmpty;
    public readonly int MinOccupiedAlpha;
    public readonly int OccupiedAlphaSpan;
    public readonly int EmptyAlpha;
    public readonly int LineAlpha;
    public readonly float LineWidth;

    public PolarStyle(
        bool fillOccupied,
        bool fillEmpty,
        int minOccupiedAlpha,
        int occupiedAlphaSpan,
        int emptyAlpha,
        int lineAlpha,
        float lineWidth)
    {
        FillOccupied = fillOccupied;
        FillEmpty = fillEmpty;
        MinOccupiedAlpha = minOccupiedAlpha;
        OccupiedAlphaSpan = occupiedAlphaSpan;
        EmptyAlpha = emptyAlpha;
        LineAlpha = lineAlpha;
        LineWidth = lineWidth;
    }

    public static readonly PolarStyle Panel = new(true, false, 55, 90, 0, 170, 1.2f);
    public static readonly PolarStyle Field = new(true, false, 14, 26, 0, 92, 1.15f);
}

internal static class PolarPainter
{
    public const int Rings = 3;
    public const int Sectors = 8;
    public const int Cells = Rings * Sectors;

    public static void Draw(Graphics g, Rectangle bounds, float[] enemy, float[] xp, float[] radii, bool fill, float[] wall = null, string blocked = "")
    {
        _ = radii;
        if (bounds.Width < 16 || bounds.Height < 16)
        {
            return;
        }

        var center = new PointF(bounds.X + bounds.Width * 0.5f, bounds.Y + bounds.Height * 0.5f);
        var outerPx = Math.Min(bounds.Width, bounds.Height) * 0.48f;
        var ringPx = new[] { 0f, outerPx * 0.34f, outerPx * 0.67f, outerPx };
        var style = fill ? PolarStyle.Panel : new PolarStyle(false, false, 0, 0, 0, 200, 1.4f);
        DrawRings(g, center, ringPx, enemy, xp, style, wall, blocked);
    }

    public static void DrawRings(Graphics g, PointF center, float[] ringPx, float[] enemy, float[] xp, PolarStyle style, float[] wall = null, string blocked = "")
    {
        if (ringPx == null || ringPx.Length < 4 || ringPx[3] < 8f)
        {
            return;
        }

        const float sweepDeg = 45f;
        const float northDeg = -90f;
        if (wall != null)
        {
            // Wall channel: grey cells, alpha follows the hit fraction. Drawn first so enemy/XP tint sits on top.
            var n = Math.Min(Cells, wall.Length);
            for (var cell = 0; cell < n; cell++)
            {
                if (wall[cell] <= 0.001f)
                {
                    continue;
                }

                var ring = cell / Sectors;
                var sector = cell % Sectors;
                var start = northDeg - sweepDeg * 0.5f + sector * sweepDeg;
                var alpha = (int)Math.Round(40 + 110 * Math.Min(1f, wall[cell]));
                using var path = AnnularSector(center, ringPx[ring], ringPx[ring + 1], start, sweepDeg);
                using var brush = new SolidBrush(Color.FromArgb(alpha, 150, 150, 160));
                g.FillPath(brush, path);
            }
        }

        if (!string.IsNullOrEmpty(blocked) && ringPx[1] > 4f)
        {
            // Bridge stuck detector: red tick on the inner ring for each cardinal side it believes is a wall.
            using var pen = new Pen(Color.FromArgb(220, 230, 70, 70), Math.Max(2f, ringPx[1] * 0.12f));
            var r = ringPx[1] * 1.05f;
            var d = r * 2f;
            foreach (var ch in blocked)
            {
                var centerDeg = ch switch
                {
                    'N' => -90f,
                    'E' => 0f,
                    'S' => 90f,
                    'W' => 180f,
                    _ => float.NaN
                };
                if (float.IsNaN(centerDeg))
                {
                    continue;
                }

                g.DrawArc(pen, center.X - r, center.Y - r, d, d, centerDeg - 28f, 56f);
            }
        }

        var maxEnemy = new float[Rings];
        var maxXp = new float[Rings];
        for (var ring = 0; ring < Rings; ring++)
        {
            maxEnemy[ring] = 1f;
            maxXp[ring] = 1f;
        }

        if (enemy != null && xp != null)
        {
            var n = Math.Min(Cells, Math.Min(enemy.Length, xp.Length));
            for (var i = 0; i < n; i++)
            {
                var ring = i / Sectors;
                if (enemy[i] > maxEnemy[ring])
                {
                    maxEnemy[ring] = enemy[i];
                }

                if (xp[i] > maxXp[ring])
                {
                    maxXp[ring] = xp[i];
                }
            }
        }

        const float sweep = 45f;
        const float northCenter = -90f;
        if ((style.FillOccupied || style.FillEmpty) && enemy != null && xp != null)
        {
            for (var ring = 0; ring < Rings; ring++)
            {
                for (var sector = 0; sector < Sectors; sector++)
                {
                    var cell = ring * Sectors + sector;
                    if (cell >= enemy.Length || cell >= xp.Length)
                    {
                        continue;
                    }

                    var occupied = enemy[cell] > 0.001f || xp[cell] > 0.001f;
                    if (!occupied && !style.FillEmpty)
                    {
                        continue;
                    }

                    var start = northCenter - sweep * 0.5f + sector * sweep;
                    using var path = AnnularSector(center, ringPx[ring], ringPx[ring + 1], start, sweep);
                    if (!occupied)
                    {
                        using var empty = new SolidBrush(Color.FromArgb(style.EmptyAlpha, 236, 208, 156));
                        g.FillPath(empty, path);
                        continue;
                    }

                    if (!style.FillOccupied)
                    {
                        continue;
                    }

                    var danger = Math.Min(1f, enemy[cell] / maxEnemy[ring]);
                    var reward = Math.Min(1f, xp[cell] / maxXp[ring]);
                    var strength = Math.Max(danger, reward);
                    var alpha = style.MinOccupiedAlpha + (int)Math.Round(style.OccupiedAlphaSpan * strength);
                    var red = (int)Math.Round(220 * danger + 48 * (1f - danger));
                    var green = (int)Math.Round(200 * reward + 36 * (1f - reward));
                    using var brush = new SolidBrush(Color.FromArgb(Math.Min(255, alpha), red, green, 36));
                    g.FillPath(brush, path);
                }
            }
        }

        using var linePen = new Pen(Color.FromArgb(style.LineAlpha, 236, 208, 156), style.LineWidth);
        for (var r = 1; r < ringPx.Length; r++)
        {
            var d = ringPx[r] * 2f;
            g.DrawEllipse(linePen, center.X - ringPx[r], center.Y - ringPx[r], d, d);
        }

        for (var sector = 0; sector < Sectors; sector++)
        {
            var deg = (northCenter - sweep * 0.5f + sector * sweep) * Math.PI / 180.0;
            var x = center.X + (float)(Math.Cos(deg) * ringPx[3]);
            var y = center.Y + (float)(Math.Sin(deg) * ringPx[3]);
            g.DrawLine(linePen, center.X, center.Y, x, y);
        }
    }

    private static GraphicsPath AnnularSector(PointF center, float rInner, float rOuter, float startDeg, float sweepDeg)
    {
        var path = new GraphicsPath();
        if (rInner < 2f)
        {
            path.AddPie(center.X - rOuter, center.Y - rOuter, rOuter * 2f, rOuter * 2f, startDeg, sweepDeg);
            return path;
        }

        var outer = new RectangleF(center.X - rOuter, center.Y - rOuter, rOuter * 2f, rOuter * 2f);
        var inner = new RectangleF(center.X - rInner, center.Y - rInner, rInner * 2f, rInner * 2f);
        path.AddArc(outer, startDeg, sweepDeg);
        path.AddArc(inner, startDeg + sweepDeg, -sweepDeg);
        path.CloseFigure();
        return path;
    }
}
