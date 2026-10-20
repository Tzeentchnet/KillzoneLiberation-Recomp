# Credits and third-party software

Killzone: Liberation Recomp is a community static-recompilation project. It is
not affiliated with or endorsed by Guerrilla, Sony Interactive Entertainment,
or the original game developers/publishers. Killzone and related names and
assets belong to their respective owners.

The repository does **not** distribute the game, a decrypted executable,
generated game code, `PSP.DAT`, `CHAPTER5.BIN`, or other copyrighted game
assets. Users must supply their own supported disc image.

## Core projects

- **PSP Recompilation Project** by sal063 provided the original static
  recompiler/runtime design. This repository pins the substantially extended
  [`Tzeentchnet/psp-recomp`](https://github.com/Tzeentchnet/psp-recomp) fork as
  a submodule. The fork's detailed provenance and per-file attribution are in
  [`external/psp-recomp/CREDITS.md`](external/psp-recomp/CREDITS.md).
- **PPSSPP** by Henrik Rydgård and contributors is the behavioral oracle for
  PSP HLE, scheduler, memory, VFPU, GE, ATRAC, and MPEG semantics. Ported and
  derived runtime code remains GPL-2.0-or-later.
- **FFmpeg ATRAC3/ATRAC3+ decoder code**, extracted into a standalone library
  by PPSSPP, is LGPL-2.1-or-later. Its source, notices, modifications, and
  license are under
  [`external/psp-recomp/third_party/at3_standalone/`](external/psp-recomp/third_party/at3_standalone/).
- **SDL3** provides native window/gamepad integration for GPU builds and is
  distributed under the zlib license.

## Platform APIs and tools

The native Windows runtime uses Direct3D 12, DXGI, DirectX Shader Compiler,
Media Foundation, XAudio2, DirectInput, and other Windows SDK interfaces.
PIX for Windows is an optional external diagnostics tool and is not
redistributed here.

Python, CMake, Ninja, clang/LLVM, GCC/MinGW, and GitHub Actions are used by the
build and verification pipeline.

## AI assistance

Parts of the runtime, renderer, tools, tests, and documentation were developed
with AI assistance. This does not change the licenses or authorship of the
human and third-party work identified above. Correctness claims are backed by
the checked-in tests and reproducible validation described in
[`WORK_DONE.md`](WORK_DONE.md), not by the use of an AI tool.

## License

The combined project is GPL-2.0-or-later; see [`LICENSE`](LICENSE). Third-party
components retain the licenses identified above.
