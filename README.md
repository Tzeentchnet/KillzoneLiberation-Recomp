# Killzone: Liberation Recomp

[![CI](https://github.com/Tzeentchnet/KillzoneLiberation-Recomp/actions/workflows/ci.yml/badge.svg)](https://github.com/Tzeentchnet/KillzoneLiberation-Recomp/actions/workflows/ci.yml)

Experimental, source-only native Windows and Apple Silicon static
recompilation of **Killzone: Liberation v1.20 (UCUS-98646)**. The PSP Allegrex
module is translated to C and linked with a game-specific HLE runtime. Windows
uses Direct3D 12, XAudio2, and Media Foundation; macOS uses SDL3 audio,
VideoToolbox for H.264 video, and the Vulkan renderer over Metal through
MoltenVK.

This project is not affiliated with or endorsed by Guerrilla or Sony
Interactive Entertainment. It does not distribute a game executable, generated
game code, disc data, saves, or other game assets.

> [!NOTE]
> **Why isn't there just an .exe to download?** Two reasons. First, safety:
> please don't download random .exe files from the internet, even from
> GitHub releases, including this one if it ever shows up! It's just good
> practice to be careful about what you run on your computer. Second, it's
> the law: this project doesn't own Killzone: Liberation, so it's not
> allowed to hand out a ready-to-play build of the game. Instead, you build
> the program yourself from this source code and combine it with a copy of
> the game disc that you already legally own. That way nobody's copyrighted
> game data ever leaves your own computer.

## Project status

| Area | Current state |
|---|---|
| Platform | Windows 10/11 x64 and macOS Apple Silicon; macOS also has a locally built, self-contained, Finder-launchable app |
| Gameplay | Windows: boot through Mission 1 completed; Apple Silicon: deterministic menu, movie, and live Mission 1 movement routes pass; full-game validation remains in progress |
| Graphics | D3D12, Vulkan, and software renderers; macOS uses Retina-aware Vulkan through MoltenVK/Metal with 1x-8x internal rendering, 1x-5x xBRZ, and SMAA 1x High |
| Audio/video/input | XAudio2 or SDL3 audio, SAS/ATRAC, keyboard/mouse, SDL gamepads, and optional twin-stick controls; H.264 PMF video uses Media Foundation on Windows and hardware-accelerated VideoToolbox on macOS |
| Saves | PSP-compatible secure savedata is implemented; full-game validation remains in progress |
| Online | Original infrastructure services are gone; ad-hoc multiplayer is not implemented |
| Distribution | Source release only; no redistributable game executable is published |

This is still a work in progress rather than a finished replacement for the
original game. Chapters 2-4, challenges, user-supplied Chapter 5, and long soak
testing remain release validation work.

## Documentation

- [Project documentation index](docs/README.md)
- [Graphics and input configuration reference](docs/CONFIGURATION.md)
- [Remaining work and release gates](docs/TODO.md)
- [Evidence-backed technical findings](docs/FINDINGS.md)
- [Original architecture and implementation plan](docs/PLAN.md)
- [Development archive](docs/WORK_DONE.md)
- [Credits and third-party provenance](CREDITS.md)

## You must supply the game

No game disc, executable, generated game C, or game asset is distributed by
this project. You must provide your own legally obtained copy of the supported
community-distributed US v1.20 image:

- Size: `568,498,176` bytes
- SHA-1: `5bc4fc8cd8d72c9c2e7c1c03a4325a29bed6e69a`

This is **not** byte-identical to Redump's retail USA disc, which is
581,632,000 bytes with SHA-1
`dda1a72c28ccdd8ddd2f3cbfd2fa3188962b0458`. See
[`research/kzl_provenance.txt`](research/kzl_provenance.txt).

The retail v1.00 disc is not interchangeable with v1.20 generated code.
Supporting it requires a separate verified extraction configuration, generated
translation units, addresses, and overrides. Bypassing the v1.20 identity
check does not produce a valid v1.00 build.

Extraction verifies that identity and the hashes of every required file.
Do not upload or commit the ISO, PRX, `PSP.DAT`, generated C, savedata, or
`CHAPTER5.BIN`; the repository ignore rules intentionally exclude them,
including the local `memstick/` tree. This project does not provide or help
locate copyrighted game data.

## Requirements

- Git with submodule support
- Python 3.11 or newer (the tested Apple setup uses Homebrew Python 3.13)
- CMake 3.25 or newer and Ninja

### Windows

- Windows 10/11 x64
- Visual Studio 2022 Build Tools with clang-cl/LLVM, MSVC v143 libraries, and
  the Windows 11 SDK
- Vulkan SDK for the combined hardware preset. A standard
  `C:\VulkanSDK\<version>` install is detected automatically.
- DirectX Shader Compiler (`dxc.exe`) only when regenerating checked-in shaders

PIX for Windows is optional but recommended for GPU debugging.

The standard preset downloads the official SDL3 3.2.20 VC development package
with a pinned SHA-256 when SDL3 is not already discoverable by CMake. Set
`KZL_FETCH_SDL3=OFF` and provide `SDL3_DIR` to require a local package instead.

### Apple Silicon

- macOS arm64 with Xcode Command Line Tools and Homebrew
- Native SDL3, Vulkan loader and headers, and MoltenVK:

```bash
brew install cmake ninja python@3.13 pkg-config \
  sdl3 vulkan-loader vulkan-headers molten-vk
```

## Build from source

Clone with the runtime fork:

```powershell
git clone --recurse-submodules https://github.com/Tzeentchnet/KillzoneLiberation-Recomp.git
Set-Location KillzoneLiberation-Recomp
```

Extract and verify the disc, then generate the translated C and relocated
image. Everything written under `build/` remains local and ignored:

```powershell
python tools\kzl\extract.py C:\path\to\Killzone_Liberation_v1.20_US.ISO
python tools\kzl\gen.py
```

Generation uses the measured boot call-target audit to place observed functions
in `/O2` translation units and all other game functions in `/O1` units. Release
builds retain precise, non-contracting floating point; startup enables x86
flush-to-zero and denormals-are-zero to match the PSP's single-precision mode.

### Windows

From a Visual Studio x64 developer shell, configure the combined hardware
build. The standard `clang-cl` preset enables D3D12 and Vulkan:

```powershell
cmake --preset clang-cl
cmake --build --preset clang-cl --target kzl_driver
```

The dependency-free software reference build remains available as a separate
preset:

```powershell
cmake --preset clang-cl-software
cmake --build --preset clang-cl-software --target kzl_driver
```

Automatic rendering selects D3D12 when it is compiled in. Run with the same
verified ISO:

```powershell
$env:PSP_ISO = 'C:\path\to\Killzone_Liberation_v1.20_US.ISO'
out\build\clang-cl\kzl.exe --boot `
  build\kzl\gen\kzl_image.bin 08804000 08804000 none --gui
```

Standalone boot rechecks the ISO size and SHA-1 before allocating guest memory;
a missing or different image exits with an explicit supported-version error.

### Apple Silicon and Metal

Extract and generate with the Homebrew Python, then use the native arm64
preset:

```bash
PYTHON=/opt/homebrew/opt/python@3.13/bin/python3.13
"$PYTHON" tools/kzl/extract.py \
  /path/to/Killzone_Liberation_v1.20_US.ISO
"$PYTHON" tools/kzl/gen.py

cmake --preset macos-arm64
cmake --build --preset macos-arm64 --target kzl_driver
```

The preset builds an arm64 Mach-O executable and selects the SDL3/Vulkan
renderer. MoltenVK translates that Vulkan work to Metal; this is the supported
Metal-backed path rather than a separate native Metal renderer.
The Vulkan window renders at the Mac display's native backing resolution,
recreates its swapchain when the drawable or display scale changes, and
supports both F11 and Control-Command-F for fullscreen. Its optional
three-pass SMAA 1x High post-process runs at the selected internal resolution.
New Mac configurations use deterministic **Automatic** quality. The policy
selects a conservative Apple-GPU tier, caps it to useful drawable detail and
Vulkan limits, and logs the choice; **Manual** retains complete control.
M1/M2 use 2x (3x for Pro/Max/Ultra), M3/M4 use 3x (4x for
Pro/Max/Ultra), and the measured M5 profile uses 4x with SMAA. Unknown devices
fall back to 2x. xBRZ remains a manual option because its measured warm-up
cost is not yet suitable for an automatic default.
The Vulkan path also persists its GE and SMAA pipeline cache under Application
Support. Cache files are accepted only for the matching device, driver,
pipeline-cache UUID, shader set, and cache schema, then replaced atomically at
clean shutdown.
At scaled internal resolutions, capable Vulkan devices upload logical
framebuffer data once and expand it with an exact nearest GPU blit instead of
CPU-expanding the host transfer. The CPU path remains available for
diagnostic A/B runs.
The macOS preset intentionally remains generic arm64 without LTO. On measured
M5 Mission 1 runs, AppleClang ThinLTO increased native guest execution time by
about 19% and grew the executable by about 96 MiB. `-mcpu=apple-m1` changed
native execution time by about -2.4% but produced no repeatable frame-time or
pacing improvement. Both experiments remained pixel-exact and were rejected
rather than becoming release defaults.

Build the local Finder-launchable app after generating the game image:

```bash
cmake --build --preset macos-arm64 --target kzl_app
open "out/build/macos-arm64/Killzone Liberation.app"
```

The app embeds SDL3, the Vulkan loader, MoltenVK, free fonts, runtime assets,
and the locally generated image. It does not copy or embed the ISO. The local
bundle is ad-hoc signed, checks that no disc image was included, and launches
without Homebrew library or Vulkan environment paths. Its third-party
libraries inherit the OS compatibility of the locally installed packages;
the protected M1 release matrix is still required before publishing a minimum
supported macOS claim.

Homebrew's Vulkan loader normally discovers MoltenVK automatically. If device
enumeration fails, point the loader at its ICD explicitly:

```bash
export VK_ICD_FILENAMES="$(brew --prefix molten-vk)/etc/vulkan/icd.d/MoltenVK_icd.json"
```

The first Finder launch opens a native picker for the verified v1.20 image,
then native graphics and controller settings. The selected ISO path is stored
under Application Support; `PSP_ISO` remains the highest-priority automation
override. The command-line development path remains available:

```bash
export PSP_ISO=/path/to/Killzone_Liberation_v1.20_US.ISO
out/build/macos-arm64/kzl --boot \
  build/kzl/gen/kzl_image.bin 08804000 08804000 none --gui
```

Some prerelease macOS SDK text stubs contain an `arm64e.x1` architecture that
older Apple linkers reject. If that exact linker error occurs and an older SDK
is installed, configure with it explicitly:

```bash
cmake --preset macos-arm64 \
  -DCMAKE_OSX_SYSROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk
```

Bounded menu, movie, and live Mission 1 movement routes have been verified
with the Vulkan GE renderer through MoltenVK on Apple Silicon. New macOS
graphics configurations use the Automatic policy described above; legacy
files migrate to Manual and retain their exact values. Select Manual and set
`internal_resolution = 1`, or use `SR_VK_SCALE=1`, to force native resolution
for diagnostics. Higher resolutions can be slower. On an Apple M5, one
normally paced first-mission test averaged
30.312, 29.979, and 29.843 game presentations/s at 2x, 3x, and 4x,
respectively, with texture scaling off. The 3x and 4x results are close to
nominal 30 FPS but do not reach 30 FPS exactly. Other scenes and hardware may
perform differently; the entire game has not been validated.

On macOS, PSMF H.264 movie video uses VideoToolbox with hardware acceleration
required and verified; ATRAC movie audio uses the shared decoder and SDL3
output. On Apple M5, a complete intro returned to the title screen with
2,432 video frames and 1,735 ATRAC frames decoded; the maximum active
audio/video timestamp separation was 8,360 ticks (about 93 ms). This is not an
end-to-end audio synchronization measurement. An independent full-file decode
produced 2,435 video and 1,752 audio frames; the in-game HLE stops earlier at
the movie's logical tail. Set `SR_MPEGLOG=1` to log decoder selection and movie
playback. If hardware decoding is unavailable, the decoder reports an error
rather than silently using software.

PSP text entry uses a native AppKit prompt on macOS. The scheduler maps PSP
threads to a native arm64 fiber context with guarded, demand-paged stacks. The
switch preserves the AArch64 nonvolatile integer registers, ABI-required SIMD
lanes, stack/frame/link registers, FPCR, and FPSR without relying on Apple's
deprecated `ucontext` API.
Native sleep/wake notifications pause and resume SDL audio, rebase scheduler
pacing so time asleep is not replayed as a catch-up burst, and force a redraw.
SDL foreground, focus, minimize, display, and controller hot-plug events clear
stale input and reopen another connected gamepad when available.

## Configuration and controls

The first Windows or macOS app launch opens native graphics and controller
settings. Run `kzl --configure` to reopen both dialogs or
`kzl --configure-input` for controller settings only.

```ini
# Windows default
renderer = d3d12
quality = manual
internal_resolution = 2
texture_scale = 1
d3d12_full_rate = 0
```

The macOS defaults are `renderer = vk` and `quality = auto`. Existing
configuration files without a `quality` entry migrate to Manual and keep
their exact resolution, texture, and anti-aliasing values.
Mutable Mac files live under
`~/Library/Application Support/KZLRecomp/`: `graphics.ini`, `input.ini`,
`launcher.ini`, and the shared `ms0` tree. Existing sibling graphics and input
files are copied there only when the destination does not already exist.
`SR_SETTINGS_DIR`, the explicit config variables, `SR_FSDIR`,
`SR_MEMSTICK`, and `PSP_ISO` continue to isolate automation.

The controller dialog's **Play Game** button saves pending bindings
and starts the game with the selected graphics settings. The build copies
`kzl_image.bin` beside the development executable and into the locally built
app's resources. The ISO remains external and is revalidated before use.

Renderer options are D3D12 (recommended on Windows, 1x-8x resolution with
1x-5x xBRZ texture scaling), Vulkan (1x-8x resolution with the same texture
scaling and SMAA 1x High), and a software reference path. `input.ini` holds the rebinding/analog configuration, including an
experimental, opt-in twin-stick scheme.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full graphics
dialog reference, the 4K path, the controller remapper, and the twin-stick
preset.

## Public verification without game data

The public [CI workflow](.github/workflows/ci.yml) uses only tracked source and
synthetic fixtures. To run its tool coverage locally:

```powershell
python -m unittest discover -s tools\tests -p "test_*.py"
python -m unittest `
  external\psp-recomp\tools\tests\test_codegen_dispatch.py `
  external\psp-recomp\tools\tests\test_ppmdiff.py `
  external\psp-recomp\tools\tests\test_tracediff.py
python tools\kzl\content_audit.py
```

The runtime-only build compiles every redistributable runtime source without
generated game code:

```powershell
cmake -S . -B out\build\runtime-only -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl `
  -DKZL_RUNTIME_ONLY=ON `
  -DBUILD_TESTING=OFF
cmake --build out\build\runtime-only --target kzl_runtime_compile
```

Full HLE, renderer, movie/audio, and protected 50-frame comparison tests require
locally generated code and a user-supplied disc; they are run only on the
trusted self-hosted workflow.
That workflow also compares the runtime's unique interpreter-fallback targets
against `config/kzl_dispatch_misses.txt`; the supported capture currently
allows no generated-dispatch misses.
Three scheduler CPU windows are also compared instruction-for-instruction
against the patched PPSSPP interpreter using
`config/kzl_scheduler_trace_points.txt`; trace files remain protected and only
the JSON pass/fail summary is retained.

## Repository layout

- `docs/` - plan, task list, findings, and development history
- `config/` - pinned disc/module configuration and codegen overrides
- `tools/kzl/` - extraction, archive, trace, and golden-frame tools
- `research/` - reproducible static/runtime analysis reports
- `external/psp-recomp/` - pinned recompiler/runtime fork
- `build/` and `out/` - ignored local generated/build output

## Releases

Every `v*` tag is published with a deterministic corresponding-source zip
containing the parent tree and the exact pinned `external/psp-recomp` tree.
Use that attached `-source.zip` rather than GitHub's automatically generated
source archive, which records only the submodule gitlink. The
[release workflow](.github/workflows/release.yml) refuses dirty or mismatched
trees and runs the content audit before publishing.

Build the same archive locally from a clean checkout with:

```powershell
python tools\kzl\source_bundle.py --version v0.1.0
```

No redistributable game executable is currently published: generated game code
and the required game data remain user-supplied and outside this repository.

## License and attribution

Project-authored and PPSSPP-derived code is licensed **GPL-2.0-or-later**; see
[LICENSE](LICENSE). The secure-savedata path includes GPL-3.0-or-later libkirk,
so linked binaries must comply with GPL-3.0-or-later. The license covers this
project's source, not the original game or its assets.

Third-party provenance and separately licensed components are documented in
[CREDITS.md](CREDITS.md) and
[external/psp-recomp/CREDITS.md](external/psp-recomp/CREDITS.md).
