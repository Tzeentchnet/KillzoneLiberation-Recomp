# Graphics and input configuration

Full reference for the Windows native graphics dialog, the controller
remapper, the portable INI files, and the experimental twin-stick scheme. See
the [README](../README.md#configuration-and-controls) for the quick-start
version.

## Graphics dialog

The native graphics dialog exposes:

- **Renderer:** Automatic, D3D12 hardware, Vulkan, or software reference.
- **Internal resolution:** 1x through 8x on D3D12 and Vulkan.
- **Texture upscaling:** Off or 2x through 5x xBRZ on hardware renderers.
- **D3D12 shading:** Balanced variable-rate shading or full-resolution
  shading.
- **Fullscreen:** F11 toggles borderless desktop fullscreen on D3D12 and
  Vulkan.

D3D12 and Vulkan scale their 512x272 logical offscreen GE target before
presenting to the desktop swapchain. On Apple Silicon, Vulkan runs through
MoltenVK and is presented by Metal. The level and player in the first mission
have been checked with this path; the rest of the game has not been fully
validated. Setting `SR_GPU=sw` selects the software GE reference renderer.

| Renderer | Internal GE resolution | Texture scaling | Role |
|---|---|---|---|
| D3D12 | 1x-8x | 1x-5x xBRZ | Recommended high-resolution renderer |
| Vulkan | 1x-8x | 1x-5x xBRZ | Hardware renderer backed by Metal on Apple Silicon |
| Software | Native PSP resolution | None | Pixel-exact reference baseline |

### Highest-quality 4K path

For the highest-quality 4K path, select D3D12, 8x internal resolution
(3840x2176), 3x or 4x xBRZ, and **Full resolution (best quality)** shading.
Press **F11** in either hardware renderer to toggle borderless desktop
fullscreen. Presentation preserves the PSP aspect ratio rather than stretching
3840x2176 to 3840x2160.

### Texture scaling and shading details

xBRZ scales decoded game textures before hardware upload. It deliberately does
not scale framebuffer or render-target textures, and higher factors can use
substantially more GPU memory. Texture scaling reduces source-texture
pixelation but cannot create detail absent from the PSP assets. D3D12 keeps
framebuffer effects on the selected physical internal-resolution grid while
retaining PSP-unit wrap, clamp, and alias offsets, matching PPSSPP's separation
of logical framebuffer dimensions from scaled render dimensions. D3D12's
**Balanced** mode uses variable-rate shading on supported GPUs; **Full
resolution** shades every internal-resolution fragment.
`SR_D3D12_VRS=0` remains available as an environment override that forces
full-rate shading.

New macOS configurations default to 1x internal resolution for performance;
other platforms default to 2x. Existing `graphics.ini` files are not changed.
Set `internal_resolution = 1` in the file beside `kzl`, or launch with
`SR_VK_SCALE=1`, to select native resolution. Set the value to `2`, `3`, or
`4` for higher internal resolutions; F11 can make the extra detail easier to
see.

On an Apple M5, a normally paced first-mission test with texture scaling off
measured game presentations over a 1,300-presentation interval:

| Internal resolution | Visible rendered size | Game presentations/s |
|---|---:|---:|
| 2x | 960x544 | 30.312 |
| 3x | 1440x816 | 29.979 |
| 4x | 1920x1088 | 29.843 |

These are averages from one route, not a whole-game guarantee. The 3x and 4x
results are close to nominal 30 FPS but remain below 30 FPS exactly. The PSP
vblank is paced at approximately 59.94 Hz, so a game presenting every other
vblank normally runs near 29.97 FPS. Performance and visual correctness in
other scenes and on other hardware remain unverified.

## Input defaults

The rebinding/analog configuration is portable: `input.ini` is created beside
`kzl.exe` on Windows or `kzl` on macOS, not under AppData. The default PC
scheme uses WASD for the analog stick, arrow keys for the D-pad, left mouse to
fire, right mouse to aim, middle mouse to reload, Space for Cross/interact, G
for grenades, and Q/E for the shoulder buttons. SDL-compatible gamepads are
mapped automatically and can be used at the same time.

Detailed binding names, keyboard/mouse controls, and runtime environment
settings are documented in
[external/psp-recomp/README.md](../external/psp-recomp/README.md).

## Controller remapper

On Windows, open the native controller remapper directly with:

```powershell
out\build\clang-cl\kzl.exe --configure-input
```

On macOS, edit `out/build/macos-arm64/input.ini`; valid changes hot-reload
while the game is running.

Each PSP action accepts up to four comma-separated gamepad inputs. Use `none`
to clear an action. For example:

```ini
gamepad.r = left_trigger
gamepad.square = west, right_trigger
```

The remapper can run in a second process while the game is running. **Save**
writes `input.ini` and hot-reloads valid changes into the game within
approximately 250 ms. The window stays open after saving so controls can be
adjusted repeatedly; select **Close** when finished. Invalid changes are
reported in the runtime log while the last valid setup remains active.

## Twin-stick controller scheme

Twin-stick controls are experimental, opt-in, and disabled by default. Enable
**Experimental twin-stick controls** in the remapper or set:

```ini
twin_stick.enabled = true
```

Enabling the mode from an off state loads this tested, editable preset:

| Input | Action |
|---|---|
| Left stick | Movement, synthesized through the PSP D-pad path |
| Right stick | On-foot facing/aim before the original target and auto-aim correction |
| LB | PSP L / strafe |
| LT | PSP R / aim |
| RT or West face button | PSP Square / fire |
| D-pad | PSP D-pad and menu navigation |

Horizontal and vertical right-stick reversal are independent remapper options;
the preset uses normal horizontal and reversed vertical aim. Centering the
right stick restores the game's original facing behavior. The temporary hidden
movement profile is applied only while a controller is connected, is not
marked dirty in the PSP save profile, and is restored on disconnect. The native
right-stick facing hook currently targets on-foot control; other gameplay
contexts retain their original aim behavior.

## Menu and content notes

The original infrastructure-mode servers are gone. Selecting **Downloads**
therefore shows an unavailable-service notice and returns to the menu instead
of handing control to the unsupported PSP bootloader downloader. User-supplied
Chapter 5 data remains supported through the mapped `ms0:` game-data folder.
The retired **KILLZONE.COM** main-menu button is non-selectable.
