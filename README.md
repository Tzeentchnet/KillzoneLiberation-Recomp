# Killzone: Liberation Recomp

Experimental native Windows static recompilation of **Killzone: Liberation
v1.20 (UCUS-98646)**. The PSP MIPS module is translated to C and linked with a
game-specific HLE runtime, Direct3D 12 renderer, XAudio2 audio, Media Foundation
movie decoder, and SDL3 window/gamepad layer.

This is a work in progress, not a finished replacement for the original game.
The deterministic automated path currently boots through the menus, Chapter 1
storyboard, and C1M1 tutorial gameplay. See [PLAN.md](PLAN.md),
[TODO.md](TODO.md), [WORK_DONE.md](WORK_DONE.md), and
[FINDINGS.md](FINDINGS.md) for exact status and evidence.

## You must supply the game

No game disc, executable, generated game C, or game asset is distributed by
this project. You must provide your own legally obtained dump of the supported
US v1.20 disc:

- Size: `568,498,176` bytes
- SHA-1: `5bc4fc8cd8d72c9c2e7c1c03a4325a29bed6e69a`

Extraction verifies that identity and the hashes of every required file.
Do not upload or commit the ISO, PRX, `PSP.DAT`, generated C, savedata, or
`CHAPTER5.BIN`; the repository ignore rules intentionally exclude them.

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

## Build from your own disc

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
`SDL3Config.cmake`:

```powershell
cmake -S . -B out\build\d3d12 -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=clang-cl `
  -DCMAKE_CXX_COMPILER=clang-cl `
  -DKZL_ENABLE_D3D12=ON `
  -DCMAKE_PREFIX_PATH=C:\path\to\SDL3
cmake --build out\build\d3d12 --target kzl_driver
```

Run with the same verified ISO:

```powershell
$env:PSP_ISO = 'C:\path\to\Killzone_Liberation_v1.20_US.ISO'
$env:SR_GPU = 'd3d12'
out\build\d3d12\kzl.exe --boot `
  build\kzl\gen\kzl_image.bin 08804000 08804000 none --gui
```

Standalone boot rechecks the ISO size and SHA-1 before allocating guest memory;
a missing or different image exits with an explicit supported-version error.

The first windowed run writes the rebinding/analog configuration to
`%LOCALAPPDATA%\KZLRecomp\input.ini`. Detailed controls and runtime environment
settings are documented in
[external/psp-recomp/README.md](external/psp-recomp/README.md).

## Public verification without game data

The public CI path compiles every redistributable runtime source without
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

The Python tools' public unit tests likewise use synthetic inputs:

```powershell
python -m unittest `
  tools\tests\test_calltargets.py `
  tools\tests\test_content_audit.py `
  tools\tests\test_golden_frames.py `
  tools\tests\test_source_bundle.py `
  external\psp-recomp\tools\tests\test_codegen_dispatch.py `
  external\psp-recomp\tools\tests\test_ppmdiff.py
python tools\kzl\content_audit.py
```

Full HLE, renderer, movie/audio, and protected 50-frame comparison tests require
locally generated code and a user-supplied disc; they are run only on the
trusted self-hosted workflow.

## Repository layout

- `config/` - pinned disc/module configuration and codegen overrides
- `tools/kzl/` - extraction, archive, trace, and golden-frame tools
- `research/` - reproducible static/runtime analysis reports
- `external/psp-recomp/` - pinned recompiler/runtime fork
- `build/` and `out/` - ignored local generated/build output

## License and attribution

The combined project is licensed **GPL-2.0-or-later**; see
[LICENSE](LICENSE). Third-party provenance and separately licensed components
are documented in [CREDITS.md](CREDITS.md) and
[external/psp-recomp/CREDITS.md](external/psp-recomp/CREDITS.md).

The license covers this project's source, not the original game or its assets.
Every `v*` tag is published with a deterministic corresponding-source zip
containing the parent tree and the exact pinned `external/psp-recomp` tree.
The release job refuses dirty or mismatched trees and runs the content audit
before publishing. Build the same archive locally from a clean checkout with:

```powershell
python tools\kzl\source_bundle.py --version v1.0.0
```

No redistributable game executable is currently published: generated game code
and the required game data remain user-supplied and outside this repository.
