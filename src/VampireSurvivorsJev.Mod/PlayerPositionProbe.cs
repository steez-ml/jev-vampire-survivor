using System.Diagnostics;
using System.Globalization;
using System.Text;
using Unity.Mathematics;
using UnityEngine;
using VampireSurvivors;
using VampireSurvivors.Data;
using VampireSurvivors.Framework;
using VampireSurvivors.Objects;
using VampireSurvivors.Objects.Characters;
using VampireSurvivors.Objects.Pickups;

namespace VampireSurvivorsJev;

internal struct EntitySlot
{
    public float X;
    public float Y;
    public float Vx;
    public float Vy;
    public float Dist2;
    public string TypeName;
}

internal struct WeaponSlot
{
    public string TypeName;
    public int Level;
    public bool Evo;
}

internal struct TypedSlot
{
    public string TypeName;
    public float X;
    public float Y;
    public float Dist2;
}

internal struct PileSlot
{
    public float X;
    public float Y;
    public float Value;
}

/// <summary>
/// Reused snapshot buffers. Polar bins and pin lists are zeroed each emit.
/// </summary>
internal sealed class GameSnapshot
{
    public const int MaxEnemies = 8;
    public const int MaxBosses = 4;
    public const int MaxChests = 8;
    public const int MaxWeapons = 12;
    public const int MaxPickups = 8;
    public const int MaxDestructibles = 8;
    public const int MaxXpPiles = 8;

    public long Seq;
    public long TMs;
    public bool Running;
    public bool Paused;
    public bool LevelUp;
    public float SurvivedSeconds;
    public bool HasPlayer;
    public float PlayerX;
    public float PlayerY;
    public float Hp;
    public float HpMax;
    public float Speed;
    public float Radius;
    public bool HasBounds;
    public float BoundsX;
    public float BoundsY;
    public float BoundsW;
    public float BoundsH;
    public int EnemyStage;
    public int EnemyPublished;
    public int GemStage;
    public int GemPublished;
    public int ChestStage;
    public int ChestPublished;
    public int BossPublished;
    public long ProbeUs;
    public float PolarR0;
    public float PolarR1;
    public float PolarR2;
    public bool HasCamera;
    public float CamSx;
    public float CamSy;
    public float CamPw;
    public float CamPh;
    public float CamR0Px;
    public float CamR1Px;
    public float CamR2Px;
    public string GameStateName = "";

    // v4 additive fields. Each group has its own Has* flag so the JSON omits what was not read.
    public bool HasProgress;
    public int Level;
    public float Xp;
    public float XpNext;
    public float Magnet;
    public int FacingX;
    public float MoveDirX;
    public float MoveDirY;
    public bool HasBlocked;
    public bool BlockedUp;
    public bool BlockedDown;
    public bool BlockedLeft;
    public bool BlockedRight;
    public int WeaponCount;
    public bool HasWall;
    public int TilemapCount;
    public int PickupStage;
    public int PickupPublished;
    public int DestructibleStage;
    public int DestructiblePublished;
    public readonly WeaponSlot[] Weapons = new WeaponSlot[MaxWeapons];
    public readonly TypedSlot[] Pickups = new TypedSlot[MaxPickups];
    public readonly TypedSlot[] Destructibles = new TypedSlot[MaxDestructibles];
    public int XpPileCount;
    public readonly PileSlot[] XpPiles = new PileSlot[MaxXpPiles];
    public readonly float[] PolarWall = new float[PolarGrid.Cells];

    public readonly EntitySlot[] Enemies = new EntitySlot[MaxEnemies];
    public readonly EntitySlot[] Bosses = new EntitySlot[MaxBosses];
    public readonly EntitySlot[] Chests = new EntitySlot[MaxChests];
    public readonly float[] PolarEnemy = new float[PolarGrid.Cells];
    public readonly float[] PolarXp = new float[PolarGrid.Cells];

    public void ResetGeometry()
    {
        HasPlayer = false;
        HasBounds = false;
        HasCamera = false;
        HasProgress = false;
        Level = 0;
        Xp = 0f;
        XpNext = 0f;
        Magnet = 0f;
        FacingX = 0;
        MoveDirX = 0f;
        MoveDirY = 0f;
        HasBlocked = false;
        BlockedUp = false;
        BlockedDown = false;
        BlockedLeft = false;
        BlockedRight = false;
        WeaponCount = 0;
        HasWall = false;
        TilemapCount = 0;
        PickupStage = 0;
        PickupPublished = 0;
        DestructibleStage = 0;
        DestructiblePublished = 0;
        XpPileCount = 0;
        Array.Clear(PolarWall, 0, PolarWall.Length);
        EnemyStage = 0;
        EnemyPublished = 0;
        GemStage = 0;
        GemPublished = 0;
        ChestStage = 0;
        ChestPublished = 0;
        BossPublished = 0;
        SurvivedSeconds = 0f;
        PlayerX = 0f;
        PlayerY = 0f;
        Hp = 0f;
        HpMax = 0f;
        Speed = 0f;
        Radius = 0f;
        CamSx = 0f;
        CamSy = 0f;
        CamPw = 0f;
        CamPh = 0f;
        CamR0Px = 0f;
        CamR1Px = 0f;
        CamR2Px = 0f;
        GameStateName = "";
        PolarR0 = SnapshotConfig.PolarR0;
        PolarR1 = SnapshotConfig.PolarR1;
        PolarR2 = SnapshotConfig.PolarR2;
        Array.Clear(PolarEnemy, 0, PolarEnemy.Length);
        Array.Clear(PolarXp, 0, PolarXp.Length);
    }
}

/// <summary>
/// Read-only harvest from this install's BepInEx interop (VampireSurvivors.Runtime.dll).
/// Types/fields below were inspected before use — do not add guessed names:
/// - GameManager.IsGameRunning, IsPaused, IsInPauseGameState, SurvivedSeconds, HardBounds
/// - GameStateMachine.CurrentState / CurrentStateName (GameStatePlaying vs GameStateLevelUp, etc.)
/// - Do not use _charactersLevelingUp.Count: that list is eligible players and stays non-empty in a run
/// - CharacterController.CurrentPos, CurrentHp, MaxHp(), Velocity, Speed; static RuntimeBodyRadiusFactor
/// - Stage.SpawnedEnemies, Stage.EnemiesCount; EnemyController.CurrentPos, Velocity, IsDead, IsBoss
/// - Stage._mainCamera (Camera); Camera.main, orthographic, orthographicSize, aspect,
///   pixelWidth/Height, WorldToScreenPoint(Vector3), ViewportToWorldPoint(Vector3)
/// - GameManager.Gems (HashSet Pickup); Pickup.position (ArcadeSprite float2), Pickup.Value, PickupType
/// - GameManager.StagePickups filtered by ItemType.TREASURE
/// v4 additions (inspected 2026-09-19 with System.Reflection.Metadata over the interop):
/// - CharacterController.Level (int), Xp (float), Magnet (MagnetZone), LastFacingDirection / IsFlipped,
///   LastMovementDirection, WeaponsManager (CharacterWeaponsManager : EquipmentManager)
/// - EquipmentManager.ActiveEquipment (List Equipment); Equipment.Type (WeaponType), Level, IsEvolution()
/// - GameManager.LevelUpFactory.XpRequiredToLevelUp (float)
/// - MagnetZone.Radius (EggFloat) -> EggFloat.GetValue()
/// - PhaserGameObject.body (BaseBody); BaseBody._blocked (ArcadeBodyCollision: up/down/left/right)
/// - Stage.HasTileSet, Stage.TilingTileset.GetPhaserTilemaps() (List PhaserTilemap);
///   PhaserTilemap.IsTileAtPosition(float2) — collision-tile probe in world units
/// - Pickup.PickupType (ItemType: ROAST = floor chicken, COIN*, VACUUM, ROSARY, OROLOGION, ...)
/// - GameManager.Destructibles (PhysicsGroup : Group) -> children (HashSet PhaserGameObject);
///   Destructible : BasePoolableSpriteBehaviour : ArcadeSprite (position), IsUnitDead(), DestructibleType (PropType)
/// v5 (2026-10-24): xp_piles are clusters of the same GameManager.Gems / Pickup.position / Pickup.Value
/// read that already fills polar.xp. No new game type.
/// v5 enemy type (inspected 2026-10-24 with System.Reflection.Metadata on this install's interop):
/// - EnemyController.EnemyType, public getter, returns VampireSurvivors.Data.EnemyType
///   (metadata: get_EnemyType_Public_get_EnemyType_0). The snapshot publishes Enum.ToString().
/// - StageEventId is a public int and is not a per-enemy id, so it is not published.
/// - EnemyController.Hp (Single) and MaxHp() (Single) were in the same pass and are not read yet.
/// - EnemyData.maxHp exists on VampireSurvivors.Data.Enemies.EnemyData, reached by CurrentEnemyData.
///   The numbers live in packed assets, not as constants, so the bridge table does not read them.
/// Inactive Unity objects are skipped via gameObject.activeInHierarchy.
/// </summary>
internal static class PlayerPositionProbe
{
    private const int WallSamplesRing0 = 6;
    private const int WallSamplesRing1 = 3;
    private const int WallSamplesRing2 = 1;

    private static GameStateMachine _stateMachine;
    private static PhaserTilemap[] _tilemaps = Array.Empty<PhaserTilemap>();
    private static readonly Stopwatch TilemapRefresh = Stopwatch.StartNew();
    private static readonly Dictionary<int, string> WeaponNames = new();
    private static readonly Dictionary<int, string> ItemNames = new();
    private static readonly Dictionary<int, string> PropNames = new();
    private static bool _wallProbeBroken;
    private static bool _weaponProbeBroken;
    private static bool _progressProbeBroken;
    private static bool _blockedProbeBroken;
    private static bool _destructibleProbeBroken;
    private static bool _xpPileBroken;
    private static bool _enemyTypeProbeBroken;
    private static readonly Dictionary<int, string> EnemyNames = new();

    public static void Fill(GameManager gameManager, GameSnapshot snapshot)
    {
        snapshot.ResetGeometry();
        if (gameManager == null)
        {
            snapshot.Running = false;
            snapshot.Paused = false;
            snapshot.LevelUp = false;
            return;
        }

        snapshot.Running = gameManager.IsGameRunning;
        snapshot.Paused = gameManager.IsPaused || gameManager.IsInPauseGameState;
        ReadGameState(snapshot);
        snapshot.SurvivedSeconds = gameManager.SurvivedSeconds;

        if (!snapshot.Running)
        {
            return;
        }

        CharacterController player = gameManager.Player;
        if (player == null)
        {
            player = gameManager.PlayerOne;
        }

        if (!IsActive(player))
        {
            return;
        }

        var pos = player.CurrentPos;
        snapshot.HasPlayer = true;
        snapshot.PlayerX = pos.x;
        snapshot.PlayerY = pos.y;
        snapshot.Hp = player.CurrentHp;
        snapshot.HpMax = player.MaxHp();
        snapshot.Speed = player.Speed;
        snapshot.Radius = CharacterController.RuntimeBodyRadiusFactor;

        ReadBounds(gameManager, snapshot);
        ReadCamera(gameManager, player, snapshot);
        ReadEnemies(gameManager, snapshot, pos);
        ReadGems(gameManager, snapshot, pos);
        ReadChests(gameManager, snapshot, pos);
        ReadProgress(gameManager, player, snapshot);
        ReadWeapons(player, snapshot);
        ReadBlocked(player, snapshot);
        ReadWalls(gameManager, snapshot, pos);
        ReadDestructibles(gameManager, snapshot, pos);
    }

    /// <summary>
    /// Braziers, candelabras and friends: the loot boxes of a stage. Published as typed pins so the
    /// bridge can weigh "maybe a chicken" against the danger on the way there.
    /// </summary>
    private static void ReadDestructibles(GameManager gameManager, GameSnapshot snapshot, Vector2 playerPos)
    {
        if (_destructibleProbeBroken || !SnapshotConfig.ProbeDestructibles)
        {
            return;
        }

        try
        {
            var group = gameManager.Destructibles;
            if (group == null)
            {
                return;
            }

            var children = group.children;
            if (children == null)
            {
                return;
            }

            var reach = snapshot.PolarR2 * 1.2f;
            var reach2 = reach * reach;
            var stage = 0;
            foreach (var child in children)
            {
                if (child == null)
                {
                    continue;
                }

                var destructible = child.TryCast<Destructible>();
                if (destructible == null || !IsActive(destructible))
                {
                    continue;
                }

                try
                {
                    if (destructible.IsUnitDead())
                    {
                        continue;
                    }
                }
                catch
                {
                }

                float x;
                float y;
                try
                {
                    var p = destructible.position;
                    x = p.x;
                    y = p.y;
                }
                catch
                {
                    continue;
                }

                stage++;
                var dist2 = Dist2(playerPos.x, playerPos.y, x, y);
                if (dist2 > reach2)
                {
                    continue;
                }

                var typeName = "";
                try
                {
                    typeName = PropTypeName(destructible.DestructibleType);
                }
                catch
                {
                }

                ConsiderTyped(snapshot.Destructibles, ref snapshot.DestructiblePublished, GameSnapshot.MaxDestructibles, typeName, x, y, dist2);
            }

            snapshot.DestructibleStage = stage;
        }
        catch (Exception ex)
        {
            _destructibleProbeBroken = true;
            snapshot.DestructiblePublished = 0;
            snapshot.DestructibleStage = 0;
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadDestructibles", "destructible read failed; probe disabled", Quote(ex));
        }
    }

    private static string PropTypeName(PropType type)
    {
        var key = (int)type;
        if (PropNames.TryGetValue(key, out var name))
        {
            return name;
        }

        name = type.ToString();
        if (string.IsNullOrEmpty(name))
        {
            name = key.ToString(CultureInfo.InvariantCulture);
        }

        PropNames[key] = name;
        return name;
    }

    private static string ItemTypeName(ItemType type)
    {
        var key = (int)type;
        if (ItemNames.TryGetValue(key, out var name))
        {
            return name;
        }

        name = type.ToString();
        if (string.IsNullOrEmpty(name))
        {
            name = key.ToString(CultureInfo.InvariantCulture);
        }

        ItemNames[key] = name;
        return name;
    }

    /// <summary>
    /// Level / XP / magnet / facing. Each read is isolated: a failing getter disables only itself
    /// for the session and is logged once, so a wrong assumption never spams or crashes the game.
    /// </summary>
    private static void ReadProgress(GameManager gameManager, CharacterController player, GameSnapshot snapshot)
    {
        if (_progressProbeBroken)
        {
            return;
        }

        try
        {
            snapshot.Level = player.Level;
            snapshot.Xp = player.Xp;
            snapshot.HasProgress = true;
        }
        catch (Exception ex)
        {
            _progressProbeBroken = true;
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadProgress", "Level/Xp read failed; progress probe disabled", Quote(ex));
            return;
        }

        try
        {
            var factory = gameManager.LevelUpFactory;
            if (factory != null)
            {
                snapshot.XpNext = factory.XpRequiredToLevelUp;
            }
        }
        catch
        {
        }

        try
        {
            var magnet = player.Magnet;
            if (magnet != null)
            {
                var radius = magnet.Radius;
                if (radius != null)
                {
                    snapshot.Magnet = radius.GetValue();
                }
            }
        }
        catch
        {
        }

        try
        {
            var facing = player.LastFacingDirection;
            if (facing.x > 0.01f)
            {
                snapshot.FacingX = 1;
            }
            else if (facing.x < -0.01f)
            {
                snapshot.FacingX = -1;
            }
        }
        catch
        {
        }

        if (snapshot.FacingX == 0)
        {
            try
            {
                // Sprites face east by default; IsFlipped means the character looks west.
                snapshot.FacingX = player.IsFlipped ? -1 : 1;
            }
            catch
            {
            }
        }

        try
        {
            var move = player.LastMovementDirection;
            snapshot.MoveDirX = move.x;
            snapshot.MoveDirY = move.y;
        }
        catch
        {
        }
    }

    /// <summary>
    /// Equipped weapons as enum names + level. Names are cached per enum value so this allocates
    /// nothing after the first frame with a given weapon.
    /// </summary>
    private static void ReadWeapons(CharacterController player, GameSnapshot snapshot)
    {
        if (_weaponProbeBroken || !SnapshotConfig.ProbeWeapons)
        {
            return;
        }

        try
        {
            var manager = player.WeaponsManager;
            if (manager == null)
            {
                return;
            }

            var active = manager.ActiveEquipment;
            if (active == null)
            {
                return;
            }

            var n = active.Count;
            for (var i = 0; i < n && snapshot.WeaponCount < GameSnapshot.MaxWeapons; i++)
            {
                Equipment equipment;
                try
                {
                    equipment = active[i];
                }
                catch
                {
                    continue;
                }

                if (equipment == null)
                {
                    continue;
                }

                var type = equipment.Type;
                var evo = false;
                try
                {
                    evo = equipment.IsEvolution();
                }
                catch
                {
                }

                snapshot.Weapons[snapshot.WeaponCount++] = new WeaponSlot
                {
                    TypeName = WeaponTypeName(type),
                    Level = equipment.Level,
                    Evo = evo
                };
            }
        }
        catch (Exception ex)
        {
            _weaponProbeBroken = true;
            snapshot.WeaponCount = 0;
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadWeapons", "weapon list read failed; weapon probe disabled", Quote(ex));
        }
    }

    private static string WeaponTypeName(WeaponType type)
    {
        var key = (int)type;
        if (WeaponNames.TryGetValue(key, out var name))
        {
            return name;
        }

        name = type.ToString();
        if (string.IsNullOrEmpty(name))
        {
            name = key.ToString(CultureInfo.InvariantCulture);
        }

        WeaponNames[key] = name;
        return name;
    }

    /// <summary>
    /// Phaser Arcade body "blocked" flags: set by the physics step when the player body was
    /// separated from a tile or immovable body on that side this frame. Raw side names are
    /// forwarded; the bridge maps up/down onto world +Y/-Y once observed in a run.
    /// </summary>
    private static void ReadBlocked(CharacterController player, GameSnapshot snapshot)
    {
        if (_blockedProbeBroken)
        {
            return;
        }

        try
        {
            var body = player.body;
            if (body == null)
            {
                return;
            }

            var blocked = body._blocked;
            snapshot.HasBlocked = true;
            snapshot.BlockedUp = blocked.up;
            snapshot.BlockedDown = blocked.down;
            snapshot.BlockedLeft = blocked.left;
            snapshot.BlockedRight = blocked.right;
        }
        catch (Exception ex)
        {
            _blockedProbeBroken = true;
            snapshot.HasBlocked = false;
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadBlocked", "body blocked read failed; blocked probe disabled", Quote(ex));
        }
    }

    /// <summary>
    /// Polar wall channel. For each of the 24 cells, a few world points inside the cell are tested
    /// against every collision tilemap with PhaserTilemap.IsTileAtPosition. Cell value = hit fraction.
    /// The tilemap list is re-fetched every 2 s (stages can add layers), otherwise cached as a plain array.
    /// </summary>
    private static void ReadWalls(GameManager gameManager, GameSnapshot snapshot, Vector2 playerPos)
    {
        if (_wallProbeBroken || !SnapshotConfig.ProbeWalls)
        {
            return;
        }

        try
        {
            var stage = gameManager.Stage;
            if (stage == null || !stage.HasTileSet)
            {
                return;
            }

            if (_tilemaps.Length == 0 || TilemapRefresh.Elapsed.TotalSeconds >= 2.0)
            {
                TilemapRefresh.Restart();
                RefreshTilemaps(stage);
            }

            var count = _tilemaps.Length;
            if (count == 0)
            {
                return;
            }

            snapshot.HasWall = true;
            snapshot.TilemapCount = count;
            var r0 = snapshot.PolarR0;
            var r1 = snapshot.PolarR1;
            var r2 = snapshot.PolarR2;
            for (var sector = 0; sector < PolarGrid.Sectors; sector++)
            {
                var center = sector * (MathF.PI / 4f);
                snapshot.PolarWall[sector] = ProbeCell(playerPos, center, 0f, r0, WallSamplesRing0);
                snapshot.PolarWall[PolarGrid.Sectors + sector] = ProbeCell(playerPos, center, r0, r1, WallSamplesRing1);
                snapshot.PolarWall[2 * PolarGrid.Sectors + sector] = ProbeCell(playerPos, center, r1, r2, WallSamplesRing2);
            }
        }
        catch (Exception ex)
        {
            _wallProbeBroken = true;
            snapshot.HasWall = false;
            snapshot.TilemapCount = 0;
            Array.Clear(snapshot.PolarWall, 0, snapshot.PolarWall.Length);
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadWalls", "tilemap probe failed; wall probe disabled", Quote(ex));
        }
    }

    private static void RefreshTilemaps(Stage stage)
    {
        var tileset = stage.TilingTileset;
        if (tileset == null)
        {
            _tilemaps = Array.Empty<PhaserTilemap>();
            return;
        }

        var list = tileset.GetPhaserTilemaps();
        if (list == null)
        {
            _tilemaps = Array.Empty<PhaserTilemap>();
            return;
        }

        var n = list.Count;
        var fresh = new List<PhaserTilemap>(n);
        for (var i = 0; i < n; i++)
        {
            PhaserTilemap map;
            try
            {
                map = list[i];
            }
            catch
            {
                continue;
            }

            if (map != null)
            {
                fresh.Add(map);
            }
        }

        _tilemaps = fresh.ToArray();
    }

    /// <summary>
    /// Sample points spread over the annular cell: 1 sample = ring midpoint on the sector centre line;
    /// 3 samples = same radius at -15/0/+15 degrees; 6 samples = those three at 40% and 85% of the span.
    /// Angle 0 is +Y (north), increasing clockwise toward +X, matching PolarGrid.SectorIndex.
    /// </summary>
    private static float ProbeCell(Vector2 origin, float centerAngle, float rLo, float rHi, int samples)
    {
        var span = rHi - rLo;
        if (span <= 0.01f)
        {
            return 0f;
        }

        var hits = 0;
        var total = 0;
        var angleCount = samples >= 3 ? 3 : 1;
        var radiusCount = samples >= 6 ? 2 : 1;
        for (var ai = 0; ai < angleCount; ai++)
        {
            var angle = centerAngle;
            if (angleCount == 3)
            {
                angle += (ai - 1) * (MathF.PI / 12f);
            }

            var dirX = MathF.Sin(angle);
            var dirY = MathF.Cos(angle);
            for (var ri = 0; ri < radiusCount; ri++)
            {
                var frac = radiusCount == 2 ? (ri == 0 ? 0.4f : 0.85f) : 0.5f;
                var radius = rLo + span * frac;
                var point = new float2(origin.x + dirX * radius, origin.y + dirY * radius);
                total++;
                if (AnyTileAt(point))
                {
                    hits++;
                }
            }
        }

        return total == 0 ? 0f : (float)hits / total;
    }

    private static bool AnyTileAt(float2 point)
    {
        var maps = _tilemaps;
        for (var i = 0; i < maps.Length; i++)
        {
            var map = maps[i];
            if (map == null)
            {
                continue;
            }

            if (map.IsTileAtPosition(point))
            {
                return true;
            }
        }

        return false;
    }

    private static string Quote(Exception ex)
    {
        var text = ex.GetType().Name + ": " + (ex.Message ?? "");
        return "{\"error\":\"" + text.Replace("\\", "\\\\").Replace("\"", "'").Replace("\n", " ").Replace("\r", " ") + "\"}";
    }

    private static void ReadCamera(GameManager gameManager, CharacterController player, GameSnapshot snapshot)
    {
        try
        {
            Camera cam = null;
            var stage = gameManager.Stage;
            if (stage != null)
            {
                cam = stage._mainCamera;
            }

            if (cam == null)
            {
                cam = Camera.main;
            }

            if (cam == null)
            {
                return;
            }

            Vector3 world;
            try
            {
                world = player.transform.position;
            }
            catch
            {
                world = new Vector3(snapshot.PlayerX, snapshot.PlayerY, 0f);
            }

            float viewR;
            if (cam.orthographic)
            {
                viewR = cam.orthographicSize;
                var halfW = viewR * cam.aspect;
                if (halfW > 0.1f && halfW < viewR)
                {
                    viewR = halfW;
                }
            }
            else
            {
                var z = Math.Abs(world.z - cam.transform.position.z);
                if (z < 0.01f)
                {
                    z = 10f;
                }

                var bl = cam.ViewportToWorldPoint(new Vector3(0f, 0f, z));
                var tr = cam.ViewportToWorldPoint(new Vector3(1f, 1f, z));
                viewR = Math.Min(Math.Abs(tr.x - bl.x), Math.Abs(tr.y - bl.y)) * 0.5f;
            }

            if (viewR < 1f)
            {
                return;
            }

            snapshot.PolarR0 = viewR * 0.28f;
            snapshot.PolarR1 = viewR * 0.58f;
            snapshot.PolarR2 = viewR * 0.95f;

            var sp = cam.WorldToScreenPoint(world);
            var pw = (float)cam.pixelWidth;
            var ph = (float)cam.pixelHeight;
            if (pw < 8f || ph < 8f)
            {
                return;
            }

            snapshot.CamSx = sp.x;
            snapshot.CamSy = ph - sp.y;
            snapshot.CamPw = pw;
            snapshot.CamPh = ph;
            snapshot.CamR0Px = ScreenDeltaX(cam, world, snapshot.PolarR0);
            snapshot.CamR1Px = ScreenDeltaX(cam, world, snapshot.PolarR1);
            snapshot.CamR2Px = ScreenDeltaX(cam, world, snapshot.PolarR2);
            snapshot.HasCamera = snapshot.CamR2Px > 2f;
        }
        catch
        {
        }
    }

    private static float ScreenDeltaX(Camera cam, Vector3 world, float radius)
    {
        var a = cam.WorldToScreenPoint(world);
        var b = cam.WorldToScreenPoint(world + new Vector3(radius, 0f, 0f));
        return Math.Abs(b.x - a.x);
    }

    private static void ReadGameState(GameSnapshot snapshot)
    {
        snapshot.LevelUp = false;
        snapshot.GameStateName = "";
        try
        {
            var machine = TryGetStateMachine();
            if (machine == null)
            {
                return;
            }

            var state = machine.CurrentState;
            var name = "";
            if (state != null)
            {
                name = state.GetType().Name;
            }

            if (string.IsNullOrEmpty(name))
            {
                name = machine.CurrentStateName ?? "";
            }

            snapshot.GameStateName = name;
            snapshot.LevelUp = IsPlayerChoiceState(state, name);
        }
        catch
        {
        }
    }

    private static GameStateMachine TryGetStateMachine()
    {
        if (IsAlive(_stateMachine))
        {
            return _stateMachine;
        }

        _stateMachine = null;
        try
        {
            _stateMachine = UnityEngine.Object.FindFirstObjectByType<GameStateMachine>();
        }
        catch
        {
            try
            {
                _stateMachine = UnityEngine.Object.FindObjectOfType<GameStateMachine>();
            }
            catch
            {
                _stateMachine = null;
            }
        }

        return IsAlive(_stateMachine) ? _stateMachine : null;
    }

    private static bool IsAlive(GameStateMachine machine)
    {
        if (machine == null)
        {
            return false;
        }

        try
        {
            return machine.gameObject != null;
        }
        catch
        {
            return false;
        }
    }

    private static bool IsPlayerChoiceState(StateMachineState state, string name)
    {
        if (state is GameStatePlaying || state is GameStatePaused || state is GameStateGameOver)
        {
            return false;
        }

        if (state is GameStateLevelUp
            || state is GameStateTreasure
            || state is GameStateWeaponSelection
            || state is GameStateLevelBonusSelection
            || state is GameStateTPWeaponSelection
            || state is GameStateItemFound
            || state is GameStateArcanaSelectionMain
            || state is GameStateSurvarotsSelection)
        {
            return true;
        }

        if (state != null)
        {
            return false;
        }

        if (string.IsNullOrEmpty(name) || name.IndexOf("GameStatePlaying", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return false;
        }

        return name.IndexOf("LevelUp", StringComparison.OrdinalIgnoreCase) >= 0
            || name.IndexOf("Treasure", StringComparison.OrdinalIgnoreCase) >= 0
            || name.IndexOf("WeaponSelection", StringComparison.OrdinalIgnoreCase) >= 0
            || name.IndexOf("BonusSelection", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static void ReadBounds(GameManager gameManager, GameSnapshot snapshot)
    {
        try
        {
            var bounds = gameManager.HardBounds;
            if (!bounds.HasValue)
            {
                return;
            }

            var rect = bounds.Value;
            snapshot.HasBounds = true;
            snapshot.BoundsX = rect.x;
            snapshot.BoundsY = rect.y;
            snapshot.BoundsW = rect.width;
            snapshot.BoundsH = rect.height;
        }
        catch
        {
        }
    }

    private static void ReadEnemies(GameManager gameManager, GameSnapshot snapshot, Vector2 playerPos)
    {
        try
        {
            var stage = gameManager.Stage;
            if (stage == null)
            {
                return;
            }

            snapshot.EnemyStage = stage.EnemiesCount;
            var spawned = stage.SpawnedEnemies;
            if (spawned == null)
            {
                return;
            }

            var r0 = snapshot.PolarR0;
            var r1 = snapshot.PolarR1;
            var r2 = snapshot.PolarR2;
            var innerLimit2 = r0 * r0;
            var n = spawned.Count;
            for (var i = 0; i < n; i++)
            {
                EnemyController enemy;
                try
                {
                    enemy = spawned[i];
                }
                catch
                {
                    continue;
                }

                if (!IsActive(enemy) || enemy.IsDead)
                {
                    continue;
                }

                var p = enemy.CurrentPos;
                var dx = p.x - playerPos.x;
                var dy = p.y - playerPos.y;
                var dist2 = dx * dx + dy * dy;
                var cell = PolarGrid.CellIndex(dx, dy, r0, r1, r2);
                snapshot.PolarEnemy[cell] += 1f;

                var isBoss = false;
                try
                {
                    isBoss = enemy.IsBoss;
                }
                catch
                {
                }

                var typeName = ReadEnemyTypeName(enemy);

                if (isBoss)
                {
                    Consider(
                        snapshot.Bosses,
                        ref snapshot.BossPublished,
                        GameSnapshot.MaxBosses,
                        p.x,
                        p.y,
                        0f,
                        0f,
                        dist2,
                        typeName);
                }

                if (dist2 < innerLimit2)
                {
                    var v = enemy.Velocity;
                    Consider(
                        snapshot.Enemies,
                        ref snapshot.EnemyPublished,
                        GameSnapshot.MaxEnemies,
                        p.x,
                        p.y,
                        v.x,
                        v.y,
                        dist2,
                        typeName);
                }
            }
        }
        catch
        {
        }
    }

    /// <summary>
    /// EnemyController.EnemyType as the enum name. A failure disables only this read.
    /// Positions, counts, and the polar grid from the same loop stay as they were.
    /// </summary>
    private static string ReadEnemyTypeName(EnemyController enemy)
    {
        if (_enemyTypeProbeBroken || !SnapshotConfig.ProbeEnemyTypes || enemy == null)
        {
            return "";
        }

        try
        {
            var type = enemy.EnemyType;
            var key = (int)type;
            if (EnemyNames.TryGetValue(key, out var cached))
            {
                return cached;
            }

            var name = type.ToString();
            if (string.IsNullOrEmpty(name))
            {
                name = key.ToString(CultureInfo.InvariantCulture);
            }

            EnemyNames[key] = name;
            return name;
        }
        catch (Exception ex)
        {
            _enemyTypeProbeBroken = true;
            DebugSessionLog.Write("P", "PlayerPositionProbe.cs:ReadEnemyTypeName", "enemy type read failed; probe disabled", Quote(ex));
            return "";
        }
    }

    private static void ReadGems(GameManager gameManager, GameSnapshot snapshot, Vector2 playerPos)
    {
        try
        {
            var gems = gameManager.Gems;
            if (gems == null)
            {
                return;
            }

            snapshot.GemStage = gems.Count;
            var r0 = snapshot.PolarR0;
            var r1 = snapshot.PolarR1;
            var r2 = snapshot.PolarR2;
            var binned = 0;
            foreach (var gem in gems)
            {
                if (!TryPickupPos(gem, out var x, out var y))
                {
                    continue;
                }

                var value = 1f;
                try
                {
                    var raw = gem.Value;
                    if (raw > 0f)
                    {
                        value = raw;
                    }
                }
                catch
                {
                }

                var cell = PolarGrid.CellIndex(x - playerPos.x, y - playerPos.y, r0, r1, r2);
                snapshot.PolarXp[cell] += value;
                binned++;
                NoteXpPile(snapshot, playerPos, x, y, value, r2);
            }

            snapshot.GemPublished = binned;
        }
        catch
        {
        }
    }

    /// <summary>
    /// Fold nearby gems into a few world-space piles. The option id is a cell of that pile,
    /// so it stays put while the player walks. A failure here disables only the piles.
    /// </summary>
    private static void NoteXpPile(GameSnapshot snapshot, Vector2 playerPos, float x, float y, float value, float r2)
    {
        if (_xpPileBroken)
        {
            return;
        }

        try
        {
            var dx = x - playerPos.x;
            var dy = y - playerPos.y;
            var reach = r2 * 1.2f;
            if (dx * dx + dy * dy > reach * reach)
            {
                return;
            }

            const float join = 2.5f;
            var n = snapshot.XpPileCount;
            for (var i = 0; i < n; i++)
            {
                var px = snapshot.XpPiles[i].X - x;
                var py = snapshot.XpPiles[i].Y - y;
                if (px * px + py * py > join * join)
                {
                    continue;
                }

                var old = snapshot.XpPiles[i].Value;
                var total = old + value;
                var pile = snapshot.XpPiles[i];
                if (total > 0.001f)
                {
                    pile.X = (pile.X * old + x * value) / total;
                    pile.Y = (pile.Y * old + y * value) / total;
                }

                pile.Value = total;
                snapshot.XpPiles[i] = pile;
                return;
            }

            if (n < GameSnapshot.MaxXpPiles)
            {
                snapshot.XpPiles[n] = new PileSlot { X = x, Y = y, Value = value };
                snapshot.XpPileCount = n + 1;
                return;
            }

            var smallest = 0;
            for (var i = 1; i < n; i++)
            {
                if (snapshot.XpPiles[i].Value < snapshot.XpPiles[smallest].Value)
                {
                    smallest = i;
                }
            }

            if (value > snapshot.XpPiles[smallest].Value)
            {
                snapshot.XpPiles[smallest] = new PileSlot { X = x, Y = y, Value = value };
            }
        }
        catch
        {
            _xpPileBroken = true;
            snapshot.XpPileCount = 0;
        }
    }

    private static void ReadChests(GameManager gameManager, GameSnapshot snapshot, Vector2 playerPos)
    {
        try
        {
            var pickups = gameManager.StagePickups;
            if (pickups == null)
            {
                return;
            }

            var n = pickups.Count;
            var stageChests = 0;
            var stagePickups = 0;
            var reach = snapshot.PolarR2 * 1.2f;
            var reach2 = reach * reach;
            for (var i = 0; i < n; i++)
            {
                Pickup pickup;
                try
                {
                    pickup = pickups[i];
                }
                catch
                {
                    continue;
                }

                if (pickup == null)
                {
                    continue;
                }

                var type = pickup.PickupType;
                if (type == ItemType.GEM)
                {
                    continue; // gems are the polar XP channel
                }

                if (!TryPickupPos(pickup, out var x, out var y))
                {
                    continue;
                }

                var dist2 = Dist2(playerPos.x, playerPos.y, x, y);
                if (type == ItemType.TREASURE)
                {
                    stageChests++;
                    Consider(snapshot.Chests, ref snapshot.ChestPublished, GameSnapshot.MaxChests, x, y, 0f, 0f, dist2);
                    continue;
                }

                stagePickups++;
                if (dist2 > reach2)
                {
                    continue;
                }

                ConsiderTyped(snapshot.Pickups, ref snapshot.PickupPublished, GameSnapshot.MaxPickups, ItemTypeName(type), x, y, dist2);
            }

            snapshot.ChestStage = stageChests;
            snapshot.PickupStage = stagePickups;
        }
        catch
        {
        }
    }

    private static void ConsiderTyped(TypedSlot[] buffer, ref int published, int cap, string typeName, float x, float y, float dist2)
    {
        var slot = new TypedSlot { TypeName = typeName ?? "", X = x, Y = y, Dist2 = dist2 };
        if (published < cap)
        {
            var i = published;
            while (i > 0 && buffer[i - 1].Dist2 > dist2)
            {
                buffer[i] = buffer[i - 1];
                i--;
            }

            buffer[i] = slot;
            published++;
            return;
        }

        if (dist2 >= buffer[published - 1].Dist2)
        {
            return;
        }

        var j = published - 1;
        while (j > 0 && buffer[j - 1].Dist2 > dist2)
        {
            buffer[j] = buffer[j - 1];
            j--;
        }

        buffer[j] = slot;
    }

    private static bool TryPickupPos(Pickup pickup, out float x, out float y)
    {
        x = 0f;
        y = 0f;
        if (!IsActive(pickup))
        {
            return false;
        }

        try
        {
            var pos = pickup.position;
            x = pos.x;
            y = pos.y;
            return true;
        }
        catch
        {
            try
            {
                var cached = pickup.cachedPosition;
                x = cached.x;
                y = cached.y;
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    private static bool IsActive(Component component)
    {
        if (component == null)
        {
            return false;
        }

        try
        {
            var go = component.gameObject;
            return go != null && go.activeInHierarchy;
        }
        catch
        {
            return false;
        }
    }

    private static float Dist2(float ax, float ay, float bx, float by)
    {
        var dx = ax - bx;
        var dy = ay - by;
        return dx * dx + dy * dy;
    }

    private static void Consider(
        EntitySlot[] buffer,
        ref int published,
        int cap,
        float x,
        float y,
        float vx,
        float vy,
        float dist2,
        string typeName = "")
    {
        var slot = new EntitySlot
        {
            X = x,
            Y = y,
            Vx = vx,
            Vy = vy,
            Dist2 = dist2,
            TypeName = typeName ?? ""
        };

        if (published < cap)
        {
            var i = published;
            while (i > 0 && buffer[i - 1].Dist2 > dist2)
            {
                buffer[i] = buffer[i - 1];
                i--;
            }

            buffer[i] = slot;
            published++;
            return;
        }

        if (dist2 >= buffer[published - 1].Dist2)
        {
            return;
        }

        var j = published - 1;
        while (j > 0 && buffer[j - 1].Dist2 > dist2)
        {
            buffer[j] = buffer[j - 1];
            j--;
        }

        buffer[j] = slot;
    }
}

internal static class SnapshotJson
{
    public static void Write(GameSnapshot snapshot, StringBuilder sb)
    {
        var inv = CultureInfo.InvariantCulture;
        sb.Clear();
        sb.Append("{\"schema_version\":5,\"seq\":");
        sb.Append(snapshot.Seq.ToString(inv));
        sb.Append(",\"t_ms\":");
        sb.Append(snapshot.TMs.ToString(inv));
        sb.Append(",\"source\":\"bepinex\",\"run\":{\"running\":");
        sb.Append(snapshot.Running ? "true" : "false");
        sb.Append(",\"paused\":");
        sb.Append(snapshot.Paused ? "true" : "false");
        sb.Append(",\"level_up\":");
        sb.Append(snapshot.LevelUp ? "true" : "false");
        sb.Append(",\"survived_seconds\":");
        AppendFloat(sb, snapshot.SurvivedSeconds);

        if (snapshot.HasPlayer)
        {
            sb.Append("},\"player\":{\"x\":");
            AppendFloat(sb, snapshot.PlayerX);
            sb.Append(",\"y\":");
            AppendFloat(sb, snapshot.PlayerY);
            sb.Append(",\"hp\":");
            AppendFloat(sb, snapshot.Hp);
            sb.Append(",\"hp_max\":");
            AppendFloat(sb, snapshot.HpMax);
            sb.Append(",\"speed\":");
            AppendFloat(sb, snapshot.Speed);
            sb.Append(",\"radius\":");
            AppendFloat(sb, snapshot.Radius);
            if (snapshot.HasProgress)
            {
                sb.Append(",\"level\":");
                sb.Append(snapshot.Level.ToString(inv));
                sb.Append(",\"xp\":");
                AppendFloat(sb, Math.Max(0f, snapshot.Xp));
                sb.Append(",\"xp_next\":");
                AppendFloat(sb, Math.Max(0f, snapshot.XpNext));
                sb.Append(",\"magnet\":");
                AppendFloat(sb, Math.Max(0f, snapshot.Magnet));
                sb.Append(",\"facing_x\":");
                sb.Append(snapshot.FacingX.ToString(inv));
                sb.Append(",\"move_dir\":[");
                AppendFloat(sb, snapshot.MoveDirX);
                sb.Append(',');
                AppendFloat(sb, snapshot.MoveDirY);
                sb.Append(']');
            }

            if (snapshot.HasBlocked)
            {
                sb.Append(",\"blocked\":[");
                var first = true;
                AppendFlag(sb, "up", snapshot.BlockedUp, ref first);
                AppendFlag(sb, "down", snapshot.BlockedDown, ref first);
                AppendFlag(sb, "left", snapshot.BlockedLeft, ref first);
                AppendFlag(sb, "right", snapshot.BlockedRight, ref first);
                sb.Append(']');
            }

            if (snapshot.WeaponCount > 0)
            {
                sb.Append(",\"weapons\":[");
                for (var i = 0; i < snapshot.WeaponCount; i++)
                {
                    if (i > 0)
                    {
                        sb.Append(',');
                    }

                    var w = snapshot.Weapons[i];
                    sb.Append("{\"type\":\"");
                    AppendSafeString(sb, w.TypeName);
                    sb.Append("\",\"level\":");
                    sb.Append(Math.Max(0, w.Level).ToString(inv));
                    sb.Append(",\"evo\":");
                    sb.Append(w.Evo ? "true" : "false");
                    sb.Append('}');
                }

                sb.Append(']');
            }

            sb.Append('}');
        }
        else
        {
            sb.Append('}');
        }

        if (snapshot.HasBounds)
        {
            sb.Append(",\"bounds\":{\"x\":");
            AppendFloat(sb, snapshot.BoundsX);
            sb.Append(",\"y\":");
            AppendFloat(sb, snapshot.BoundsY);
            sb.Append(",\"w\":");
            AppendFloat(sb, snapshot.BoundsW);
            sb.Append(",\"h\":");
            AppendFloat(sb, snapshot.BoundsH);
            sb.Append('}');
        }

        sb.Append(",\"polar\":{\"rings\":3,\"sectors\":8,\"radii\":[");
        AppendFloat(sb, snapshot.PolarR0);
        sb.Append(',');
        AppendFloat(sb, snapshot.PolarR1);
        sb.Append(',');
        AppendFloat(sb, snapshot.PolarR2);
        sb.Append("],\"enemy\":[");
        WriteFloatArray(sb, snapshot.PolarEnemy);
        sb.Append("],\"xp\":[");
        WriteFloatArray(sb, snapshot.PolarXp);
        if (snapshot.HasWall)
        {
            sb.Append("],\"wall\":[");
            WriteFloatArray(sb, snapshot.PolarWall);
        }

        sb.Append("]},\"enemies\":[");
        WriteEntities(sb, snapshot.Enemies, snapshot.EnemyPublished, true);
        sb.Append("],\"bosses\":[");
        WriteEntities(sb, snapshot.Bosses, snapshot.BossPublished, false);
        sb.Append("],\"chests\":[");
        WriteEntities(sb, snapshot.Chests, snapshot.ChestPublished, false);
        sb.Append("],\"pickups\":[");
        WriteTyped(sb, snapshot.Pickups, snapshot.PickupPublished);
        sb.Append("],\"destructibles\":[");
        WriteTyped(sb, snapshot.Destructibles, snapshot.DestructiblePublished);
        if (snapshot.XpPileCount > 0)
        {
            sb.Append("],\"xp_piles\":[");
            for (var i = 0; i < snapshot.XpPileCount; i++)
            {
                if (i > 0)
                {
                    sb.Append(',');
                }

                var pile = snapshot.XpPiles[i];
                sb.Append("{\"x\":");
                AppendFloat(sb, pile.X);
                sb.Append(",\"y\":");
                AppendFloat(sb, pile.Y);
                sb.Append(",\"value\":");
                AppendFloat(sb, Math.Max(0f, pile.Value));
                sb.Append('}');
            }
        }

        sb.Append("],\"counts\":{\"enemies_stage\":");
        sb.Append(snapshot.EnemyStage.ToString(inv));
        sb.Append(",\"enemies_published\":");
        sb.Append(snapshot.EnemyPublished.ToString(inv));
        sb.Append(",\"gems_stage\":");
        sb.Append(snapshot.GemStage.ToString(inv));
        sb.Append(",\"gems_published\":");
        sb.Append(snapshot.GemPublished.ToString(inv));
        sb.Append(",\"chests_stage\":");
        sb.Append(snapshot.ChestStage.ToString(inv));
        sb.Append(",\"chests_published\":");
        sb.Append(snapshot.ChestPublished.ToString(inv));
        sb.Append(",\"bosses_published\":");
        sb.Append(snapshot.BossPublished.ToString(inv));
        sb.Append(",\"tilemaps\":");
        sb.Append(snapshot.TilemapCount.ToString(inv));
        sb.Append(",\"pickups_stage\":");
        sb.Append(snapshot.PickupStage.ToString(inv));
        sb.Append(",\"pickups_published\":");
        sb.Append(snapshot.PickupPublished.ToString(inv));
        sb.Append(",\"destructibles_stage\":");
        sb.Append(snapshot.DestructibleStage.ToString(inv));
        sb.Append(",\"destructibles_published\":");
        sb.Append(snapshot.DestructiblePublished.ToString(inv));
        sb.Append("},\"perf\":{\"probe_us\":");
        sb.Append(snapshot.ProbeUs.ToString(inv));
        sb.Append("}}");
    }

    private static void WriteFloatArray(StringBuilder sb, float[] values)
    {
        for (var i = 0; i < values.Length; i++)
        {
            if (i > 0)
            {
                sb.Append(',');
            }

            AppendFloat(sb, values[i]);
        }
    }

    private static void WriteEntities(StringBuilder sb, EntitySlot[] slots, int count, bool velocity)
    {
        for (var i = 0; i < count; i++)
        {
            if (i > 0)
            {
                sb.Append(',');
            }

            var e = slots[i];
            sb.Append("{\"x\":");
            AppendFloat(sb, e.X);
            sb.Append(",\"y\":");
            AppendFloat(sb, e.Y);
            if (velocity)
            {
                sb.Append(",\"vx\":");
                AppendFloat(sb, e.Vx);
                sb.Append(",\"vy\":");
                AppendFloat(sb, e.Vy);
            }

            if (!string.IsNullOrEmpty(e.TypeName))
            {
                sb.Append(",\"type\":\"");
                AppendSafeString(sb, e.TypeName);
                sb.Append('"');
            }

            sb.Append('}');
        }
    }

    private static void WriteTyped(StringBuilder sb, TypedSlot[] slots, int count)
    {
        for (var i = 0; i < count; i++)
        {
            if (i > 0)
            {
                sb.Append(',');
            }

            var e = slots[i];
            sb.Append("{\"type\":\"");
            AppendSafeString(sb, e.TypeName);
            sb.Append("\",\"x\":");
            AppendFloat(sb, e.X);
            sb.Append(",\"y\":");
            AppendFloat(sb, e.Y);
            sb.Append('}');
        }
    }

    private static void AppendFloat(StringBuilder sb, float value)
    {
        if (float.IsNaN(value) || float.IsInfinity(value))
        {
            sb.Append('0');
            return;
        }

        sb.Append(value.ToString("0.###", CultureInfo.InvariantCulture));
    }

    private static void AppendFlag(StringBuilder sb, string name, bool on, ref bool first)
    {
        if (!on)
        {
            return;
        }

        if (!first)
        {
            sb.Append(',');
        }

        first = false;
        sb.Append('"');
        sb.Append(name);
        sb.Append('"');
    }

    private static void AppendSafeString(StringBuilder sb, string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return;
        }

        foreach (var ch in value)
        {
            if (ch == '"' || ch == '\\' || ch < ' ')
            {
                sb.Append('_');
            }
            else
            {
                sb.Append(ch);
            }
        }
    }
}
