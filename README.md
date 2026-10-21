# Killzone: Liberation Recomp

[![CI](https://github.com/Tzeentchnet/KillzoneLiberation-Recomp/actions/workflows/ci.yml/badge.svg)](https://github.com/Tzeentchnet/KillzoneLiberation-Recomp/actions/workflows/ci.yml)

Experimental, source-only native Windows static recompilation of
**Killzone: Liberation v1.20 (UCUS-98646)**. The PSP Allegrex module is
translated to C and linked with a game-specific HLE runtime, Direct3D 12
renderer, XAudio2 audio, Media Foundation movie decoder, and SDL3
window/gamepad layer.

This project is not affiliated with or endorsed by Guerrilla or Sony
Interactive Entertainment. It does not distribute a game executable, generated
game code, disc data, saves, or other game assets.

## Project status

| Area | Current state |
|---|---|
| Platform | Windows 10/11 x64; clang-cl and Direct3D 12 are the primary path |
| Gameplay | Boot, menus, the Chapter 1 presentation, tutorial, and Mission 1 have been completed |
| Graphics | Native D3D12 renderer, software reference path, and 1x-8x internal scaling; 2x is the measured default |
| Audio/video/input | XAudio2, SAS/ATRAC, Media Foundation PMF playback, keyboard/mouse, and SDL gamepads are implemented |
| Saves | PSP-compatible secure savedata is implemented; full-game validation remains in progress |
| Online | Original infrastructure services are gone; ad-hoc multiplayer is not implemented |
| Distribution | Source release only; no redistributable game executable is published |

This is still a work in progress rather than a finished replacement for the
original game. Chapters 2-4, challenges, user-supplied Chapter 5, and long soak
testing remain release validation work.

## Documentation

- [Project documentation index](docs/README.md)
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

Extraction verifies that identity and the hashes of every required file.
Do not upload or commit the ISO, PRX, `PSP.DAT`, generated C, savedata, or
`CHAPTER5.BIN`; the repository ignore rules intentionally exclude them,
including the local `memstick/` tree. This project does not provide or help
locate copyrighted game data.

## Requirements

- Windows 10/11 x64
- Git with submodule support
- Python 3.11 or newer
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools:
  - clang-cl/LLVM tools
  - MSVC v143 libraries
  - Windows 11 SDK
- SDL3 development package for the D3D12 window/input build
- DirectX Shader Compiler (`dxc.exe`) only when regenerating checked-in shaders

PIX for Windows is optional but recommended for GPU debugging.

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

From a Visual Studio x64 developer shell, configure the native D3D12 build.
Point `CMAKE_PREFIX_PATH` at the SDL3 package directory containing
`SDL3Config.cmake`. The standard `clang-cl` preset enables D3D12:

```powershell
cmake --preset clang-cl -DCMAKE_PREFIX_PATH=C:\path\to\SDL3
cmake --build --preset clang-cl --target kzl_driver
```

D3D12 hardware rendering is selected automatically in a D3D12-enabled build.
Set `SR_GPU=sw` only when the reference CPU rasterizer is needed for comparison.
Run with the same verified ISO:

```powershell
$env:PSP_ISO = 'C:\path\to\Killzone_Liberation_v1.20_US.ISO'
out\build\clang-cl\kzl.exe --boot `
  build\kzl\gen\kzl_image.bin 08804000 08804000 none --gui
```

Standalone boot rechecks the ISO size and SHA-1 before allocating guest memory;
a missing or different image exits with an explicit supported-version error.

## Configuration and controls

The first windowed run opens a native graphics launcher. It defaults to D3D12
at 2x internal resolution (960x544), then writes `graphics.ini` beside
`kzl.exe`. Run `kzl.exe --configure` to reopen it, or edit the portable file:

```ini
renderer = d3d12
internal_resolution = 2
```

At scaled resolutions, supported GPUs keep geometry, coverage, and depth at
the selected resolution while shading direct draws at PSP-native fragment
density. This avoids multiplying the original game's heavy framebuffer effects
by four or sixteen; set `SR_D3D12_VRS=0` to force full-rate fragment shading.

The rebinding/analog configuration is also portable: `input.ini` is created
beside `kzl.exe`, not under AppData. The default PC scheme uses WASD for the
analog stick, arrow keys for the D-pad, left mouse to fire, right mouse to aim,
middle mouse to reload, Space for Cross/interact, G for grenades, and Q/E for
the shoulder buttons. SDL-compatible gamepads are mapped automatically and can
be used at the same time. Detailed controls and runtime environment settings are documented in
[external/psp-recomp/README.md](external/psp-recomp/README.md).

The original infrastructure-mode servers are gone. Selecting **Downloads**
therefore shows an unavailable-service notice and returns to the menu instead
of handing control to the unsupported PSP bootloader downloader. User-supplied
Chapter 5 data remains supported through the mapped `ms0:` game-data folder.
The retired **KILLZONE.COM** main-menu button is non-selectable.

Higher internal resolutions are available but remain experimental. The 2x
default is the validated performance/quality target.

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
