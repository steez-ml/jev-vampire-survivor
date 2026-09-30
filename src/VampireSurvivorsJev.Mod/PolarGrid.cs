namespace VampireSurvivorsJev;

/// <summary>
/// 3 rings × 8 sectors around the player. Sector 0 is +Y (north / W key), then clockwise.
/// Index = ring * 8 + sector. Distances beyond the outer radius still land in ring 2
/// so a far gem pile is visible. Angle uses atan2(dx, dy) so 0 is +Y, increasing toward +X.
/// </summary>
internal static class PolarGrid
{
    public const int Rings = 3;
    public const int Sectors = 8;
    public const int Cells = Rings * Sectors;

    public static readonly string[] SectorNames = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };

    public static int CellIndex(float dx, float dy, float r0, float r1, float r2)
    {
        var dist = MathF.Sqrt(dx * dx + dy * dy);
        var ring = 2;
        if (dist < r0)
        {
            ring = 0;
        }
        else if (dist < r1)
        {
            ring = 1;
        }
        else if (dist < r2)
        {
            ring = 2;
        }

        var sector = SectorIndex(dx, dy);
        return ring * Sectors + sector;
    }

    public static int SectorIndex(float dx, float dy)
    {
        if (dx * dx + dy * dy < 1e-8f)
        {
            return 0;
        }

        var angle = MathF.Atan2(dx, dy);
        angle += MathF.PI / 8f;
        var twoPi = MathF.PI * 2f;
        if (angle < 0f)
        {
            angle += twoPi;
        }

        if (angle >= twoPi)
        {
            angle -= twoPi;
        }

        var sector = (int)(angle / twoPi * Sectors);
        if (sector < 0)
        {
            return 0;
        }

        if (sector >= Sectors)
        {
            return 0;
        }

        return sector;
    }

    public static string HottestXpSector(float[] xp)
    {
        var best = -1;
        var bestVal = 0f;
        for (var i = 0; i < xp.Length; i++)
        {
            if (xp[i] > bestVal)
            {
                bestVal = xp[i];
                best = i;
            }
        }

        if (best < 0)
        {
            return "—";
        }

        return SectorNames[best % Sectors];
    }

    public static float InnerEnemyMass(float[] enemy)
    {
        var sum = 0f;
        var n = Math.Min(Sectors, enemy.Length);
        for (var i = 0; i < n; i++)
        {
            sum += enemy[i];
        }

        return sum;
    }
}
