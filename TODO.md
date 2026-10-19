# TODO — Killzone Liberation D3D12 recomp

The live task list. When an item is done, tick it **and** move a one-line entry into [WORK_DONE.md](WORK_DONE.md)
with the date. `→ F-xxx` points to the finding that motivates the task. Phases match [PLAN.md](PLAN.md#3-phases-and-exit-criteria).

Priority: **P0** blocks the next milestone · **P1** is needed for 1.0 · **P2** is nice to have or a stretch goal.

---

## Phase 0 — Environment and repo
- [x] **T-0.1 P0** Install VS 2022 Build Tools (MSVC v143 + clang-cl), Windows 11 SDK (d3d12, dxgi, DXC) and PIX for Windows. → F-041
  *2026-10-19: MSVC 14.44, clang-cl 19.1.5, SDK 10.0.26100 (with dxc) and Ninja are in. PIX moves to T-4.14 (needed only for GPU debugging).*
- [x] **T-0.2 P0** `git init`, plus a `.gitignore` that excludes `*.ISO`, `*.PRX`, `*.DAT`, `CHAPTER5.BIN`, `/build`, `/gen` and `/external/*/build`.
- [x] **T-0.3 P0** Fork `sal063/PSP-recompilation-project` and add it as the submodule `external/psp-recomp`. Pin `da17b0e`. → F-040
  *Done as a private mirror, `Tzeentchnet/psp-recomp` (`main` = upstream `da17b0e`, our work on `kzl`).*
- [ ] **T-0.4 P1** MSYS2 UCRT64 (gcc, sdl3, vulkan-loader, lld): build unmodified sal063 against one homebrew ELF to get a known-good baseline.
- [ ] **T-0.5 P0** Get the PPSSPP desktop build and `PPSSPPHeadless.exe`. Confirm KZL boots there and capture a reference log.
- [ ] **T-0.6 P1** Add `LICENSE` (GPL-2.0-or-later), `CREDITS.md` (PPSSPP, sal063) and a README stating that the user supplies the game.
- [ ] **T-0.7 P1** CI skeleton (GitHub Actions, windows-latest): run the Python tools' unit tests and do a compile-only build of the runtime without game code.

## Phase 1 — Extraction and static analysis
- [x] **T-1.1 P0** `tools/kzl/extract.py`: check the ISO SHA-1 (F-001), then pull out KZL.PRX, BOOT.BIN, PARAM.SFO and the PSP.DAT header. Built from `tools/survey/isols.py`.
- [x] **T-1.2 P0** Pin `config/kzl.toml`: `base=0x08804000`, `entry=module_start=0x08804000`, the start-thread params and the ISO hash. → F-010
- [ ] **T-1.3 P1** Ghidra project: load KZL.PRX with the Allegrex/PSP loader (for example `pspsdk` or `ghidra-allegrex`). Apply NID names from `research/kzl_imports.toml`.
- [ ] **T-1.4 P1** Identify statically linked libraries and label their functions: Havok (version string `** Havok libs built with version [`), Lua 4.0, libgu, SN runtime and libc. Use FLIRT-style signatures or PPSSPP's `knownfuncs`. → F-012, F-013
- [ ] **T-1.5 P1** Recover the RTTI/vtable layout (`.data` pointer tables) to name C++ classes, starting with the SV* classes. → F-014
- [x] **T-1.6 P0** Reverse BOOT.BIN to find the exact `sceKernelLoadModule` path and flags, the `sceKernelStartModule` argp (`-patch_failed`?), and the memory layout it expects. → F-004
- [x] **T-1.7 P1** `tools/kzl/pspdat.py`: list the PSP.DAT TOC (dirs, names, offsets, sizes) and confirm the 12-byte record hypothesis. → F-020
- [ ] **T-1.10 P2** Work out PSP.DAT header words `[2]`/`[3]` (0xFA3E01/0xFA3DB6) and whether the game checks them. → F-020
- [ ] **T-1.11 P2** Find the game's PSP.DAT reader (the function that opens `disc0:/PSP_GAME/USRDIR/PSP.DAT` and walks the TOC) and confirm which duplicate copy it picks. → F-020
- [ ] **T-1.8 P2** Function-match KZL.PRX against KZL.PRX.100 to carry names between versions and see what 1.20 changed.
- [ ] **T-1.9 P2** Check the plaintext-PRX provenance against Redump / a known-good retail dump. → F-003

## Phase 2 — Recompiler completion
- [x] **T-2.1 P0** Codegen: `bvf/bvt/bvfl/bvtl` (cop2 rs=8). 25 functions. → F-016
- [x] **T-2.2 P0** Codegen: `vfad` (VFPU9 0x06). 24 functions.
- [x] **T-2.3 P0** Codegen: the VFPU7 conversion group (VFPU4 jump 0x01). 9 functions.
- [x] **T-2.4 P0** Codegen: the remaining BSHFL sub-ops (SPECIAL3 0x20). 9 functions.
- [x] **T-2.5 P0** Codegen: `vi2f` (VFPU4 jump 0x14, 6 functions), VFPU6 sub 4 (probably `vmscl`, 3 functions), and `cache` as a no-op (1 function).
- [x] **T-2.6 P0** **Jump-table pass:** detect `sltiu/beqz … lui/addiu; sll; addu; lw; jr rX` at the 243 sites, then emit a `switch` with local labels. Separate tail calls from switches. → F-017
  *Analysis done: 240 tables / 4,480 cases in `research/kzl_jumptables.toml`, the rest in `config/kzl_overrides.toml` (F-018, F-019). `codegen_ext.emit_switch_jr()` is tested and wired in.*
- [ ] **T-2.7 P0** Check function boundaries: run PPSSPPHeadless with a block trace, collect every executed `jal`/`jalr` target, then diff against the 42,641-entry inventory. Feed misses into `overrides.toml`. → F-015
- [x] **T-2.8 P0** **Split the output:** codegen writes `gen/kzl_recomp_NNN.c` (about 1 MB each, about 200 files) plus `gen/kzl_dispatch.c` (a sorted address→fn table with binary search or a perfect hash). → F-016
  *Done: `codegen.py --split` (via `tools/kzl/gen.py`) writes `kzl_recomp.h`, 230 TUs and `kzl_recomp_register.c`. The sorted dispatch table is split out as T-2.14.*
- [ ] **T-2.14 P1** Replace sal063's 65,536-slot dispatch hash with a table generated at build time (sorted array or perfect hash) in `kzl_recomp_register.c`. → F-043
- [ ] **T-2.9 P1** Add a CMake target for the generated code: clang-cl `/O2` for hot code and `/O1` for the rest, no `/fp:fast`, `/fp:precise` with FTZ/DAZ set at startup. Target a full build in under 10 min on 8 cores. → F-013
  *2026-10-19: `CMakeLists.txt` + `CMakePresets.json` (preset `clang-cl`, Ninja, Release) build `kzl_game.lib` from the 231 TUs in 49 s with 0 warnings. Still to do: the runtime target and the exe (with T-3.1), cold-code `/O1`, and FTZ/DAZ at startup.*
- [ ] **T-2.10 P1** Link the interpreter fallback (`src/ref/interp.cpp`) for dispatch misses. Log every miss once and keep a regression list.
- [ ] **T-2.11 P1** Trace-diff gate: `tracediff.py` against PPSSPP for the first 5M instructions after `module_start`, run in CI on a self-hosted runner with the user's ISO.
- [x] **T-2.13 P0** Wire `codegen_ext.py` into the forked codegen: try `codegen_ext.effect()` before the base decoder; add `bv*` to `is_cond_branch/cond_expr/is_likely`; in `function_flow`, follow switch and computed-goto targets as intra-function labels; emit `jr` through `emit_switch_jr()`; treat `[[jal_next]]` as link-only; read the jump register before the delay slot for every `jr`/`jalr` (F-019). Exit: 0 trapping stubs and no `jr` to an unknown label. Needs T-0.3. → F-016, F-018, F-019
  *Done: 42,300/42,300 functions, 0 stubs, all TUs pass `gcc -fsyntax-only -Wall` (also fixed the analyzer's stale-`lui` bug, F-015).*
- [ ] **T-2.12 P2** Codegen performance: keep the GPRs in locals within a function, elide `sr_begin/sr_end` hooks in release builds, and turn constant-address `jalr` into direct calls.

## Phase 3 — Runtime and HLE bring-up (headless)
- [ ] **T-3.1 P0** Loader: map the image at 0x08804000, apply relocations at runtime (or use the prxload image), run `.ctors`/`.cplinit`, create the start thread (prio 0x20, stack 0x400) and call `module_start` with the T-1.6 argv.
- [ ] **T-3.2 P0** Fake-load `BINPSP/mpeg.prx` through ModuleMgr and route sceMpeg to HLE. → F-032
- [ ] **T-3.3 P0** VFS: `disc0:` → the ISO (`iso.c`); `ms0:`/`fatms0:` → `%LOCALAPPDATA%/KZLRecomp/ms0`; the game's `cache:` device → the same tree, so `CHAPTER5.BIN` can be found. → F-021
- [ ] **T-3.4 P0** ThreadMan gaps: Fpl (`Create/Delete/TryAllocateFpl`), `DelayThreadCB`, `CheckCallback`, `DeleteCallback`, `ReferThreadStatus`, `GetThreadExitStatus`, `GetThreadmanIdList`, `SysClock2USec`. → F-031
- [ ] **T-3.5 P0** IoFileMgr gaps: `Dopen/Dread/Dclose`, `Remove`, `Rmdir`, `ChangeAsyncPriority`.
- [ ] **T-3.6 P0** GE list HLE: `ListSync`, `ListEnQueueHead`, `ListUpdateStallAddr`, `Break`, `Continue`, `UnsetCallback`, with correct signal/finish callback order. → F-033
- [ ] **T-3.7 P0** Networking: stub every sceNet\*/Http/Ssl/Apctl/Resolver/Adhoc\*/OpenPSID import so it returns "WLAN switch off" or not connected. Check that the game shows `ERROR_WLAN_SWITCH_OFF` cleanly. → F-022
- [ ] **T-3.8 P1** sceUtility: MsgDialog (native, through the sal063 GUI), Netconf (cancel), GameSharing (cancel), Load/UnloadUsbModule and UnloadAvModule (succeed), and `GetSystemParamString` (nickname).
- [ ] **T-3.9 P1** Umd: `ReplaceProhibit`, `UnRegisterUMDCallBack`, `Deactivate`. Also Ctrl, Rtc, Utils, Impose and Power leftovers.
- [ ] **T-3.10 P0** Headless milestone: boot to the main-menu loop, dump GE display lists to disk, and record that no unimplemented NID was hit.
- [ ] **T-3.11 P1** Savedata: check that sal063's `savedata.c` handles KZL's `SaveableData` header and hash (see the "SaveableData" error strings). Saves should round-trip with PSP/PPSSPP saves.
- [ ] **T-3.12 P1** Make sure the SVBrowser reads local `.jsp` pages through sceIo and not sceHttp. → F-014

## Phase 4 — D3D12 GE backend
### 4a: first image (milestone M1)
- [ ] **T-4.1 P0** Define or confirm the `GeBackend` interface from `ge_shared.h` and `gpu_sdl3vk/ge_gpu.h`, and restructure it so Vulkan and D3D12 are interchangeable at runtime (`SR_GPU=d3d12|vk|sw`).
- [ ] **T-4.2 P0** `src/gpu_d3d12/device.cpp`: adapter selection, device, queues, fences, flip-model swapchain on the SDL3 HWND, descriptor heaps (a CBV/SRV/UAV ring and an RTV/DSV pool), and an upload ring buffer.
- [ ] **T-4.3 P0** Port `psp_vert.inc` and `psp_frag.inc` to HLSL (`shaders/psp_vs.hlsl`, `psp_ps.hlsl`), with a DXC build step producing embedded DXIL.
- [ ] **T-4.4 P0** Root signature: per-draw root constants or CBV for GE state, SRVs for the texture and CLUT, and static samplers plus dynamic sampler descriptors.
- [ ] **T-4.5 P0** CPU vertex decoder into the upload ring: all GE vertex formats, through-mode, indices. Rectangles (`PRIM_RECTANGLES`) expanded to quads.
- [ ] **T-4.6 P0** PSO cache keyed by a hash of the GE state, with a synchronous fallback at first.
- [ ] **T-4.7 P0** Present path: display framebuffer → back buffer with aspect-correct scaling (480×272 is 16:9).
### 4b: correctness
- [ ] **T-4.8 P0** Texture cache: hash by address+size+CLUT, unswizzle, CLUT4/8 palettes, DXT1/3/5 and all 16/32-bit formats, mip levels, and invalidation on CPU writes or block transfers.
- [ ] **T-4.9 P0** Framebuffer cache and VRAM aliasing: render-to-texture, copies on format or stride changes, `sceGeEdram` CPU reads with lazy readback, and block transfer (`TRXKICK`) emulation.
- [ ] **T-4.10 P0** Depth (16-bit range and `minz/maxz`), stencil-as-alpha, alpha/color test, color doubling, fog, texture function modes and dithering in HLSL.
- [ ] **T-4.11 P1** Blending: all GE equations, including absdiff and fixed colors. Logic ops through a shader path or a framebuffer copy.
- [ ] **T-4.12 P1** Bezier/spline patches (CPU tessellation), morph weights and skinning (CPU).
- [ ] **T-4.13 P0** Golden-frame harness: capture 50 frames (boot, menu, C1M1 gameplay, a cutscene and the HUD) from the PPSSPP software renderer, then `ppmdiff.py` against the D3D12 output in CI.
- [ ] **T-4.14 P1** Debug tooling (install PIX for Windows first): PIX markers per list and draw, a GE state dump on hotkey, and a `SR_GPU_LOG` equivalent for D3D12.
### 4c: performance
- [ ] **T-4.15 P1** Async PSO compilation, an `ID3D12PipelineLibrary` disk cache and an ubershader fallback, so there are no first-use hitches.
- [ ] **T-4.16 P2** Decode vertices in the shader from raw GE buffers, batch draws within a list, and cache constant-buffer state.

## Phase 5 — Audio, video, input
- [ ] **T-5.1 P0** SasCore gaps: ADSR (`SetADSR`, `SetADSRmode`, `SetSimpleADSR`, `SetSL`), reverb (`RevType`, `RevParam`, `RevEVOL`, `RevVON`), noise and pause. → F-031
- [ ] **T-5.2 P0** sceAudio `Output2*` (SRC channel). Mic input stubbed to "no device".
- [ ] **T-5.3 P1** Atrac3+ gaps: `GetBufferInfoForResetting` and `GetInternalErrorInfo`. Confirm looping BGM.
- [ ] **T-5.4 P1** PMF movies (intro, attract, credits): `sceMpegAvcDecodeMode`, and check that Media Foundation decodes H.264 baseline at 480×272 with A/V sync.
- [ ] **T-5.5 P0** Input: SDL3 gamepad plus keyboard, a rebinding config, and analog dead-zone and curve settings.
- [ ] **T-5.6 P2** Pick the audio backend (XAudio2 or SDL3). Measure latency against vblank-paced audio.

## Phase 6 — Game completeness
- [ ] **T-6.1 P0** Play through chapters 1–4 and log crashes and visual bugs as issues, each with a GE dump.
- [ ] **T-6.2 P1** Challenges mode, unlockables and rewards (Lua-driven, so check the save flags).
- [ ] **T-6.3 P1** Chapter 5: the user puts `CHAPTER5.BIN` in the ms0 data folder, and `HasChapter5` turns true. Play chapter 5. → F-021
- [ ] **T-6.4 P1** A 10-hour soak test that watches the memory heap (the 32 MB PSP-1000 limit is emulated), thread starvation and audio drift.
- [ ] **T-6.5 P2** Ad-hoc co-op and versus over LAN: map `sceNetAdhoc*` to UDP, following PPSSPP's adhoc and AdhocServer design.
- [ ] **T-6.6 P2** Investigate `debugoptions.jsp` and how to unlock the debug menu. → F-014

## Phase 7 — Enhancements
- [ ] **T-7.1 P1** Internal resolution scaling (×2…×8) with correct handling of framebuffer readback and copies.
- [ ] **T-7.2 P2** MSAA or SSAA, and anisotropic filtering.
- [ ] **T-7.3 P2** Frame rate: check whether game logic is tied to vblank. Then add an interpolated or 60 fps option, or keep 30 locked.
- [ ] **T-7.4 P2** Texture dump and replacement, through the texture-cache hash.
- [ ] **T-7.5 P2** Config UI (an ImGui overlay): graphics, input, paths and the Chapter 5 file picker.

## Phase 8 — Release
- [ ] **T-8.1 P1** Startup check: SHA-1 of the ISO, with a clear error if the ISO is missing or wrong.
- [ ] **T-8.2 P1** Audit that no copyrighted payloads are in the repo or releases (no ISO, PRX, DAT, generated C from the game, or fonts we can't redistribute).
- [ ] **T-8.3 P1** GPL source bundle published with every binary.
