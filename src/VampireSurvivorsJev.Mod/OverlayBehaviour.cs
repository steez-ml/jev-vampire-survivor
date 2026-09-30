using System;
using UnityEngine;

namespace VampireSurvivorsJev;

/// <summary>
/// Read-only IMGUI overlay hosted as an injected Unity MonoBehaviour.
///
/// BepInEx IL2CPP plugins do not get MelonLoader's OnGUI callback. Instead we
/// register this class with IL2CPP and let Unity call OnGUI each frame.
/// The IntPtr constructor is required: IL2CPP creates the native object, then
/// hands us the pointer to wrap.
///
/// Player x,y is a later step. This overlay only draws Hello world.
/// </summary>
public sealed class OverlayBehaviour : MonoBehaviour
{
    private bool _loggedGui;

    public OverlayBehaviour(IntPtr pointer)
        : base(pointer)
    {
    }

    private void Awake()
    {
        DontDestroyOnLoad(gameObject);
        DebugSessionLog.Write("L", "OverlayBehaviour.cs:Awake", "overlay behaviour Awake");
    }

    private void OnGUI()
    {
        if (!_loggedGui)
        {
            _loggedGui = true;
            DebugSessionLog.Write("L", "OverlayBehaviour.cs:OnGUI", "first OnGUI");
        }

        GUI.Box(new Rect(12f, 12f, 340f, 48f), "Hello world");
    }
}
