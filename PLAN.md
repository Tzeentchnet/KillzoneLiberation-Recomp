# Killzone Liberation: Windows / Direct3D 12 static recompilation plan

**Goal:** a native Windows x64 executable that runs *Killzone: Liberation* (UCUS-98646 v1.20) from a disc image
the user supplies. The game's MIPS code is statically recompiled to C, system calls are high-level emulated (HLE),
and the PSP GPU (the GE) is rendered through **Direct3D 12**. We ship no Sony or Guerrilla assets or code.

Companion documents:
- [TODO.md](TODO.md) — the live task list, with IDs `T-x.y`
- [WORK_DONE.md](WORK_DONE.md) — a dated archive of finished work
- [FINDINGS.md](FINDINGS.md) — facts about the target, with IDs `F-xxx`

---

## 1. Starting point (see FINDINGS for the evidence)

- The game is a single **plaintext PRX** (`USRDIR/KZL.PRX`), so there is no decryption step (F-003).
  The bootloader can be skipped (F-004).
- The sal063 toolkit **already recompiles every one of the 42,641 discovered functions**. 77 of them are trapping
  stubs from 7 unhandled opcode classes (F-015, F-016). There is no jump-table recovery yet (F-017).
- **159 of the 300 imports** already have HLE. About 69 of the missing ones are networking and can be stubbed (F-031).
- The engine includes Lua 4.0 (F-012), Havok (F-013) and an SVML-based UI (F-014).
- Chapter 5 comes from an external `CHAPTER5.BIN` (F-021).

What is left is mostly **engineering work, not unknowns**. The largest new piece is the D3D12 GE backend.

## 2. Architecture

```
            offline (Python, build time)                         runtime (C/C++, Windows x64)
 ┌──────────────────────────────────────────────┐      ┌──────────────────────────────────────────────────┐
 │ ISO ─▶ iso extract ─▶ KZL.PRX                │      │ kzl.exe                                          │
 │            │                                 │      │  ├─ loader: maps image @0x08804000, applies      │
 │            ├─▶ prxload  (relocate @0x08804000)│      │  │   relocs, runs .ctors, starts module_start   │
 │            ├─▶ analyze  (42.6k functions)    │      │  ├─ recompiled code (kzl_recomp_000..NNN.c)     │
 │            ├─▶ imports  (300 NIDs)           │─────▶│  │   + dispatch table + jump-table switches     │
 │            ├─▶ jumptab  (243 computed jumps) │      │  ├─ interpreter fallback (src/ref/interp.cpp)    │
 │            └─▶ codegen  ─▶ N split C files   │      │  ├─ HLE kernel: threads, sync, memory, IO, UMD  │
 │ overrides.toml (hand fixes, hooks)           │      │  │   savedata, utility dialogs, net=offline      │
 └──────────────────────────────────────────────┘      │  ├─ media: SAS/Atrac3+ ─▶ XAudio2/SDL3 audio     │
                                                       │  │          PSMF/H.264 ─▶ Media Foundation       │
                                                       │  ├─ GE command processor (ge.c, reused)          │
                                                       │  │    └─▶ GeBackend interface (ge_shared.h)      │
                                                       │  │          ├─ D3D12 backend   ◀── NEW, primary  │
                                                       │  │          ├─ Vulkan backend  (sal063, A/B ref) │
                                                       │  │          └─ software raster (oracle/debug)    │
                                                       │  └─ platform: SDL3 window/input, XInput, config  │
                                                       └──────────────────────────────────────────────────┘
 Verification: PPSSPPHeadless traces ⇄ tracediff.py ;  frame dumps ⇄ ppmdiff.py ;  VFPU fuzz ⇄ vfpu_fuzz_gen.py
```

### Key decisions
| # | Decision | Reason |
|---|---|---|
| D1 | **Fork sal063** as the base (it stays GPL-2.0+) and keep it as an upstream remote. The fork is the private mirror `Tzeentchnet/psp-recomp` (`main` = upstream, our work on `kzl`), used as the submodule `external/psp-recomp`. | It already handles KZL at 99.8% function coverage. Rewriting it would cost months. A private mirror keeps the work private until release. |
| D2 | **Write a native D3D12 backend** behind the existing `ge_shared.h` boundary, without SDL_GPU | We need full control of VRAM aliasing, readback, depth and stencil tricks, logic ops and the PSO cache. The SDL_GPU D3D12 path stays a fallback idea. |
| D3 | **Port sal063's GLSL `psp_vert`/`psp_frag` to HLSL, compiled with DXC (SM 6.0+)** | It keeps the GE semantics that sal063 validated against PPSSPP. |
| D4 | **Build with CMake and clang-cl**, with codegen output split into about 200 TUs | 237 MB in one TU does not compile (F-016). clang-cl gives PDBs for PIX and VS debugging. The generated code uses GNU C (`__builtin_clz`, statement expressions), which MSVC `cl` rejects (F-045). |
| D5 | **Skip the bootloader** and load KZL.PRX directly | It is a thin loader (F-004). We copy only the argv and memory layout it sets up. |
| D6 | **Offline only for 1.0.** Networking reports "WLAN off". Ad-hoc over UDP is a stretch goal. | The servers are gone (F-022). It removes about 69 imports from the critical path. |
| D7 | **The user supplies the ISO.** The runtime reads `disc0:` from it, with a hash check. | Legal hygiene, and no asset extraction pipeline to maintain. |
| D8 | **PPSSPP is the oracle** for HLE results, CPU traces and GE output | It gives deterministic diffing in place of guesswork. |

## 3. Phases and exit criteria

Detailed tasks are in [TODO.md](TODO.md). Effort estimates assume one experienced developer, in weeks.

| Phase | Name | Exit criteria | Est. |
|---|---|---|---|
| **0** | Environment and repo | Toolchain installed. sal063 forked as a submodule. Its Vulkan reference build runs a homebrew sample. PPSSPP and PPSSPPHeadless are available. | 0.5 |
| **1** | Extraction and static analysis | Reproducible `extract → relocate → analyze → imports` from the ISO hash. Ghidra project with the PRX loaded. Libraries identified (Havok, Lua, libgu, SN runtime). PSP.DAT lister. Bootloader → KZL argv documented. | 1–2 |
| **2** | Recompiler completion | **0 trapping stubs.** Jump tables recovered. Output split into N TUs that build in under 10 min. Trace diff against PPSSPP matches for the first 5M instructions after `module_start`. | 2–3 |
| **3** | Runtime/HLE bring-up (headless) | KZL boots headless and reaches the main-menu loop. GE lists are submitted and dumped. No unimplemented-NID aborts on the boot → main menu → mission 1 load path. | 3–4 |
| **4** | **D3D12 GE backend** | Main menu and chapter 1 mission 1 render correctly. Per-frame ppmdiff against the PPSSPP software renderer is under threshold on a 50-frame golden set. No D3D12 debug-layer errors. | 5–7 |
| **5** | Audio, video, input | Music, SFX and voice are correct (SAS + Atrac3+). Intro and credits PMF movies play. Gamepad and keyboard work and can be rebound. | 2 |
| **6** | Game completeness | Chapters 1–4 and challenges complete. Saves work and are compatible with PSP saves. Chapter 5 runs from a user-supplied `CHAPTER5.BIN`. No crashes in a 10-hour soak. | 3–4 |
| **7** | Enhancements | Internal resolution scaling, MSAA, an uncapped or 60 fps option if the logic allows, texture filtering options, a borderless window, and a config UI. | 2–3 |
| **8** | Release hygiene | GPL source release, no copyrighted payloads, ISO-hash check, installer or zip, docs. | 1 |

Total: about **20–27 developer-weeks** to a full 1.0. **Milestone M1** is the first image on screen (end of phase 4a).
**Milestone M2** is the first playable mission.

## 4. D3D12 backend design notes (phase 4)

Mapping PSP GE features to D3D12 is where most of the risk sits:
- **Device and swapchain:** flip-model swapchain, 3 frames in flight, fence per frame. Internal 480×272 render
  targets scaled up at present time. Debug layer and GPU-based validation in Debug builds. PIX markers for each
  GE list and each draw.
- **VRAM model:** the PSP draws to framebuffers at VRAM addresses (0x04000000+, 2 MB). We keep a
  **framebuffer cache keyed by `{fb_addr, stride, format}`**, each entry a D3D12 render target. When the CPU or a
  texture fetch hits the same address, we copy or resolve (render-to-texture, block transfers, and CPU readback
  only on demand). PPSSPP's `FramebufferManager` is the reference.
- **Formats:** RT 5650 / 5551 / 4444 / 8888, rendered internally as RGBA8 and converted in the shader. Textures:
  swizzled linear, CLUT4/8/16/32, DXT1/3/5, 565 / 5551 / 4444 / 8888. CLUT goes in a separate SRV, with
  palette lookup in the shader.
- **Vertices:** decode GE vertex formats on the CPU into an upload ring buffer to start. Optimise later by
  decoding in the shader from raw bytes. Through-mode, bezier/spline (CPU tessellation at first), and
  morph/skinning (decoded on the CPU).
- **Pipeline state:** PSO key = a hash of blend, depth, stencil, cull, color-mask and topology state plus the
  shader variant. Async PSO creation with an on-disk `ID3D12PipelineLibrary` cache, and an ubershader fallback
  while a specialized PSO compiles. This avoids hitches.
- **Fixed-function emulation in HLSL:** alpha test, color test, color doubling, fog, texture function modes,
  dithering, and min/max/absdiff blends. Logic ops use a shader path (D3D12 logic ops only work on UINT RTs).
  Blends with fixed colors that cannot be expressed use dual-source blending or programmable blending through
  ROV or a copy.
- **Depth:** 16-bit PSP depth range, emulated with D32 and range remapping. `minz`/`maxz` clipping goes in
  the shader.
- **Stencil:** the PSP shares stencil with destination alpha. Use a D24S8/D32S8X24 stencil plus alpha
  write-back, as PPSSPP does.

## 5. Major risks

| Risk | Mitigation |
|---|---|
| Float behavior differs from the PSP (Havok, AI) | FTZ/DAZ on, no FMA contraction, sal063's VFPU sin/cos/rcp approximations, and fuzz checks against PPSSPP |
| Threading and timing: the game assumes PSP thread priorities, vblank and GE interrupt order | Keep sal063's cooperative scheduler (`sched.c`), and emulate vblank and GE callbacks on a virtual clock |
| Compile time and memory for about 3M lines of generated C | Split TUs, use `/O1` on cold code, unity-build options, ccache/sccache, and cache incremental codegen by function hash |
| Missed function boundaries and indirect targets | The interpreter fallback (`src/ref/interp.cpp`) plus a dispatch-miss log that feeds `overrides.toml` |
| VRAM aliasing and readback stalls in D3D12 | A framebuffer cache with lazy readback, plus per-game hacks recorded in `overrides.toml` |
| GPL obligations | Publish everything. Never redistribute the ISO, PRX, assets or CHAPTER5.BIN. |
| ISO provenance (plaintext PRX, F-003) | Pin the SHA-1 and support only that build at first. KZL.PRX.100 stays a later target. |

## 6. Repository layout (target)

```
/                          plan docs (this file, TODO, WORK_DONE, FINDINGS)
/external/psp-recomp       fork of sal063 (submodule -> private mirror, branch kzl)
/external/ppsspp           reference only (not linked), optional
/tools/survey              reproducible static-survey scripts (done)
/tools/kzl                 KZL-specific tools: extract, PSP.DAT lister, disassembler, jump-table pass, gen
/config/kzl.toml           ISO hash, load base, entry, boot argv
/config/kzl_overrides.toml hand-checked codegen overrides
/src/gpu_d3d12             new D3D12 GE backend + HLSL shaders
/src/platform              window, input, config, paths (cache:/ms0: mapping)
/research                  raw outputs of analysis runs (small text only)
/build, /gen               ignored: generated C, objects, the exe
```
