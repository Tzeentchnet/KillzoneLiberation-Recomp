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
- [x] **T-0.5 P0** Get the PPSSPP desktop build and `PPSSPPHeadless.exe`. Confirm KZL boots there and capture a reference log.
  *Desktop 1.20.4 (official zip, SHA-256 checked) in `D:\Tools\PPSSPP-1.20.4`; PPSSPPHeadless built from the v1.20.4 tag in `D:\Github\ppsspp` (`Windows\x64\Release\PPSSPPHeadless.exe`). Both boot KZL (F-047).*
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
- [x] **T-2.7 P0** Check function boundaries: run PPSSPPHeadless with a block trace, collect every executed `jal`/`jalr` target, then diff against the 42,641-entry inventory. Feed misses into `overrides.toml`. → F-015
  *Done 2026-10-19: the PPSSPP patch now emits compact unique call edges. A 90-second deterministic boot capture recorded 12,399 edges and 4,553 in-module targets; all are covered by the current effective 42,600-function inventory. The only executed analyzer seed removed by codegen is the already-overridden `jal .+8` get-PC target at 0x08B21928. No new boundary overrides were needed (F-060).*
- [x] **T-2.8 P0** **Split the output:** codegen writes `gen/kzl_recomp_NNN.c` (about 1 MB each, about 200 files) plus `gen/kzl_dispatch.c` (a sorted address→fn table with binary search or a perfect hash). → F-016
  *Done: `codegen.py --split` (via `tools/kzl/gen.py`) writes `kzl_recomp.h`, 230 TUs and `kzl_recomp_register.c`. The sorted dispatch table is split out as T-2.14.*
- [ ] **T-2.14 P1** Replace sal063's 65,536-slot dispatch hash with a table generated at build time (sorted array or perfect hash) in `kzl_recomp_register.c`. → F-043
- [ ] **T-2.9 P1** Add a CMake target for the generated code: clang-cl `/O2` for hot code and `/O1` for the rest, no `/fp:fast`, `/fp:precise` with FTZ/DAZ set at startup. Target a full build in under 10 min on 8 cores. → F-013
  *2026-10-19: `CMakeLists.txt` + `CMakePresets.json` (preset `clang-cl`, Ninja, Release) build `kzl_game.lib` from the 231 TUs in 49 s with 0 warnings. Still to do: the runtime target and the exe (with T-3.1), cold-code `/O1`, and FTZ/DAZ at startup.*
- [ ] **T-2.10 P1** Link the interpreter fallback (`src/ref/interp.cpp`) for dispatch misses. Log every miss once and keep a regression list.
- [ ] **T-2.11 P1** *Oracle side done (2026-10-19): `tools/ppsspp/psprecomp-trace.patch` + `tools/kzl/ppsspp_trace.py`, F-048. The runtime side works for `module_start` (F-049). Still to do: scheduler-mode traces, several start points because the first 5M steps are mostly one sort loop, handling of kernel-trampoline steps, and a streaming diff for multi-GB traces.* Trace-diff gate: `tracediff.py` against PPSSPP for the first 5M instructions after `module_start`, run in CI on a self-hosted runner with the user's ISO.
- [x] **T-2.13 P0** Wire `codegen_ext.py` into the forked codegen: try `codegen_ext.effect()` before the base decoder; add `bv*` to `is_cond_branch/cond_expr/is_likely`; in `function_flow`, follow switch and computed-goto targets as intra-function labels; emit `jr` through `emit_switch_jr()`; treat `[[jal_next]]` as link-only; read the jump register before the delay slot for every `jr`/`jalr` (F-019). Exit: 0 trapping stubs and no `jr` to an unknown label. Needs T-0.3. → F-016, F-018, F-019
  *Done: 42,300/42,300 functions, 0 stubs, all TUs pass `gcc -fsyntax-only -Wall` (also fixed the analyzer's stale-`lui` bug, F-015).*
- [ ] **T-2.12 P2** Codegen performance: keep the GPRs in locals within a function, elide `sr_begin/sr_end` hooks in release builds, and turn constant-address `jalr` into direct calls.

## Phase 3 — Runtime and HLE bring-up (headless)
- [x] **T-3.1 P0** Loader: map the image at 0x08804000, apply relocations at runtime (or use the prxload image), run `.ctors`/`.cplinit`, create the start thread (prio 0x20, stack 0x400) and call `module_start` with the T-1.6 argv.
  *Done 2026-10-19: `kzl.exe --boot` loads the pre-relocated `kzl_image.bin` without an oracle trace and synthesizes PPSSPP's exact `module_start` thread: UID 0x11C, stack 0x09FFFC00..0x0A000000, k0 0x09FFFF00, sp 0x09FFFEB0, `module_start(11, "modulename")`, and ra 0x08000030. The module's own init path runs from its real entry, creates `user_main` as UID 0x11D, and reaches SELECT YOUR LANGUAGE in strict mode (F-059).*
- [x] **T-3.13 P0** Port PPSSPP's `BlockAllocator` (`Core/Util/BlockAllocator.cpp`) to the runtime: first fit, 256-byte grain, low/high/fixed-address placement, free, and failure when full. Rebuild `sceKernelAllocPartitionMemory`/`FreePartitionMemory`/`MaxFreeMemSize`/`TotalFreeMemSize`, thread stacks (from the partition top, as PPSSPP does), and Fpl/Vpl on it. Blocks T-3.4: KZL's start-up memory probe overruns the current bump allocator (F-049).
  *Done 2026-10-19: fork `src/rt/kmem.c` (port checked against PPSSPP's own code by `tools/tests/test_kmem_blockalloc.py`, 320k random ops, 0 mismatches). Partition memory, FPLs and thread stacks are built on it. Threads now start with PPSSPP's register state, stack fill, k0 block and argument copy. KZL's memory probe matches PPSSPP call for call (F-050). Vpl is not imported by KZL, so it is not ported.*
- [ ] **T-3.14 P1** Keep kernel UIDs in step with PPSSPP across the bootloader exit: during KZL's first `sceKernelDelayThread`, BOOT.BIN's `sceKernelStopUnloadSelfModuleWithStatus` makes PPSSPP create a "bootloader" thread (UID 0x11E), so from the first DummyHeap FPL every handle we return is one lower than the oracle's. Either model the bootloader exit (consume the UID at that point) or let the trace diff accept a known UID offset. Needed for scheduler-mode trace diffs (T-2.11). The same applies to GE list IDs: BOOT.BIN used 41, so PPSSPP's first KZL list is 0x35000029 and ours is 0x35000000 (carry `nextListID` in the trace header). → F-050, F-051
- [x] **T-3.2 P0** Fake-load `BINPSP/mpeg.prx` through ModuleMgr and route sceMpeg to HLE. → F-032, F-058
  *Done 2026-10-19: corrected PSMF timestamp parsing, moved ring consumption from AU retrieval to timestamp-driven decode, and preserved decoder-buffered tail frames after the ring drains. The 81.248 s intro now produces the same 2,435 AVC decodes plus one no-data AU as patched PPSSPP, then follows the same flush/free/unregister/delete/destruct/finish lifecycle (F-058).*
- [x] **T-3.3 P0** VFS: `disc0:` → the ISO (`iso.c`); `ms0:`/`fatms0:` → `%LOCALAPPDATA%/KZLRecomp/ms0`; the game's `cache:` device → the same tree, so `CHAPTER5.BIN` can be found. → F-021, F-057
  *Done 2026-10-19: writable devices now default to `%LOCALAPPDATA%\KZLRecomp\ms0` (`SR_FSDIR` remains a test/developer override), preserve hierarchy, and share one tree across `ms0:`, `fatms0:` and `cache:`. The focused HLE test round-trips `cache:CHAPTER5.BIN` through all three aliases; a strict scheduled boot with the default mapping reached frame 1,200 (F-057).*
*Boot-path priority for T-3.4 to T-3.9: the 22 functions marked MISSING in `research/ppsspp_boot_hle_60s.txt` (F-047).*
- [x] **T-3.4 P0** ThreadMan gaps: ~~Fpl (`Create/Delete/TryAllocateFpl`)~~ (done in T-3.13), ~~`DelayThreadCB`, `CheckCallback`, `DeleteCallback`~~ (done: kernel callbacks, F-052), `ReferThreadStatus`, `GetThreadExitStatus`, `GetThreadmanIdList`, `SysClock2USec`. → F-031, F-054
  *Done 2026-10-19: thread metadata/exit status and typed UID enumeration now follow PPSSPP, including filtered thread lists and the 108-byte modern `SceKernelThreadInfo`; focused ABI tests cover success, truncation and error paths (F-054).*
- [x] **T-3.5 P0** IoFileMgr gaps: `Dopen/Dread/Dclose`, `Remove`, `Rmdir`, `ChangeAsyncPriority`, and PPSSPP-style asynchronous worker/delay behavior. → F-052, F-054, F-055
  *Done 2026-10-19: hierarchical host paths, ISO9660 directories, stats/removal, and a reusable priority-controlled `SceIoAsync` helper thread now pass the focused HLE suite. Async operations expose pending/ready/consumed states, busy errors, delayed waits and deferred close instead of completing inline (F-055).*
- [x] **T-3.6 P0** GE list HLE: `ListSync`, `ListEnQueueHead`, `ListUpdateStallAddr`, `Break`, `Continue`, `UnsetCallback`, with correct signal/finish callback order. → F-033
  *Done 2026-10-19: fork `src/rt/gelist.c` ports PPSSPP's list manager and GE interrupt handler; `src/rt/intr.c` the sub-interrupt table. KZL's libgu signal path matches PPSSPP's log (F-051).*
- [x] **T-3.7 P0** Networking: stub every sceNet\*/Http/Ssl/Apctl/Resolver/Adhoc\*/OpenPSID import so it returns "WLAN switch off" or not connected. Check that the game shows `ERROR_WLAN_SWITCH_OFF` cleanly. → F-022, F-056
  *Done 2026-10-19: all 69 networking imports plus the two sceWlan imports have deterministic offline HLE. A strict scripted JOIN GAME run initializes and tears down the ad-hoc stack, then renders "NETWORK ERROR OCCURRED, WLAN SWITCH HAS BEEN TURNED OFF" without an unimplemented NID.*
- [ ] **T-3.8 P1** sceUtility: MsgDialog (native, through the sal063 GUI), Netconf (cancel), GameSharing (cancel), Load/UnloadUsbModule and UnloadAvModule (succeed), and `GetSystemParamString` (nickname).
- [x] **T-3.9 P1** Umd: `ReplaceProhibit`, `UnRegisterUMDCallBack`, `Deactivate`. Also Ctrl, Rtc, Utils, Impose and Power leftovers.
  *Done 2026-10-19 (F-053): the UMD calls with the UMD callback, `sceCtrlPeekBufferPositive`/`SetSamplingCycle`, `sceRtcGetCurrentTick`/`GetTime_t`, the Dcache and GPI calls, `sceImpose{Get,Set}LanguageMode`, the scePower callbacks.*
- [x] **T-3.10 P0** Headless milestone: boot to the main-menu loop, dump GE display lists to disk, and record that no unimplemented NID was hit.
  *Done 2026-10-19 (F-053): strict mode reaches SELECT YOUR LANGUAGE and, with `SR_PADSCRIPT`, the PLAY A GAME main menu (~6,800 vblanks, no unimplemented NID). `SR_DLDUMP=<vblank>` dumps a frame's display lists.*
- [ ] **T-3.11 P1** Savedata: check that sal063's `savedata.c` handles KZL's `SaveableData` header and hash (see the "SaveableData" error strings). Saves should round-trip with PSP/PPSSPP saves.
- [ ] **T-3.12 P1** Make sure the SVBrowser reads local `.jsp` pages through sceIo and not sceHttp. → F-014

## Phase 4 — D3D12 GE backend
### 4a: first image (milestone M1)
- [x] **T-4.1 P0** Define or confirm the `GeBackend` interface from `ge_shared.h` and `gpu_sdl3vk/ge_gpu.h`, and restructure it so Vulkan and D3D12 are interchangeable at runtime (`SR_GPU=d3d12|vk|sw`).
  *Done 2026-10-19: the old draw-only `GeGpuHooks` table is now a named `GeBackend` descriptor with init, present, shutdown, primitive, flush, invalidation, and block-transfer callbacks. `SR_GPU=sw|vk|d3d12` is parsed centrally by the GUI path; unavailable/invalid backends fail explicitly, while unset and legacy variables preserve the current software defaults. The existing Vulkan implementation exports the same descriptor that T-4.2 will provide for D3D12 (F-061).*
- [x] **T-4.2 P0** `src/gpu_d3d12/device.cpp`: adapter selection, device, queues, fences, flip-model swapchain on the SDL3 HWND, descriptor heaps (a CBV/SRV/UAV ring and an RTV/DSV pool), and an upload ring buffer.
  *Done 2026-10-19: `src/rt/gpu_d3d12/device.cpp` selects a high-performance adapter (or explicit WARP), owns direct/copy queues and timeline fences, presents through a three-buffer flip-discard swapchain created from SDL3's Win32 HWND, partitions shader-visible descriptors and a 24 MiB upload ring by frame, and provides reusable RTV/DSV pools. `SR_GPU=d3d12` is now runnable by uploading the software-GE framebuffer while T-4.3 through T-4.7 add the native shader path (F-062).*
- [x] **T-4.3 P0** Port `psp_vert.inc` and `psp_frag.inc` to HLSL (`shaders/psp_vs.hlsl`, `psp_ps.hlsl`), with a DXC build step producing embedded DXIL.
  *Done 2026-10-19: native Shader Model 6.0 vertex/pixel ports preserve the Vulkan shader's 32-byte vertex ABI, noperspective varyings, texture functions, alpha/depth tests, fog, clear mode, and doubled-source-alpha handling, with D3D's required Y transform. A deterministic Python/DXC generator writes hash-stamped embedded byte arrays; Make and CMake expose regenerate/check targets, and reflection locks the 64-byte `b0` plus `t0`/`s0` interface (F-063).*
- [x] **T-4.4 P0** Root signature: per-draw root constants or CBV for GE state, SRVs for the texture and CLUT, and static samplers plus dynamic sampler descriptors.
  *Done 2026-10-19: the live root signature uses 16 pixel-stage DWORD constants at `b0`, one two-entry `t0` texture/`t1` CLUT table, a dynamic `s0` sampler table, and static clamp-nearest `s1`/clamp-linear `s2`. A 768-entry shader-visible sampler ring is partitioned across the three fenced frames; each reset binds the signature, both heaps, safe null SRVs, zero state, and a default dynamic sampler (F-064).*
- [x] **T-4.5 P0** CPU vertex decoder into the upload ring: all GE vertex formats, through-mode, indices. Rectangles (`PRIM_RECTANGLES`) expanded to quads.
  *Done 2026-10-19: D3D12 now captures the authoritative post-decode `GeVtx` seam, so `ge.c` continues to own all raw formats, skinning, through mode, index widths, transforms, and clipping. Triangles pack into the shader's asserted 32-byte ABI; rectangles, lines, and points expand into triangle-list quads with matching Vulkan semantics. Primitive boundaries and perspective flags accompany fenced upload-ring slices while hooks still return to the reference rasterizer until native draws become the presentation source (F-065).*
- [x] **T-4.6 P0** PSO cache keyed by a hash of the GE state, with a synchronous fallback at first.
  *Done 2026-10-19: every captured batch snapshots a canonical 16-byte PSO key covering mapped blend/alpha operations, color writes, depth, culling, and attachment formats. A 512-entry FNV-1a/open-addressed cache verifies full keys on collision, creates embedded-HLSL graphics PSOs synchronously on first use, and binds cached objects on later batches. Hardware, WARP, and a 1,200-frame stress create the same five PSOs with no failures or exhaustion while software presentation remains authoritative (F-066).*
- [x] **T-4.7 P0** Present path: display framebuffer → back buffer with aspect-correct scaling (480×272 is 16:9).
  *Done 2026-10-19: each software-GE frame is copied into a persistent 480×272 BGRA8 texture, then a dedicated fullscreen-triangle PSO samples it into the true SDL pixel-sized flip buffer. Resizing drains the graphics queue and recreates all three back buffers; every present clears the output black and uses the exact 480:272 aspect with centered letterbox or pillarbox bars. Focused layout tests, hardware/WARP boots, live wide/portrait resizing, and a 1,200-frame hardware stress pass (F-067).*
### 4b: correctness
- [x] **T-4.8 P0** Texture cache: hash by address+size+CLUT, unswizzle, CLUT4/8 palettes, DXT1/3/5 and all 16/32-bit formats, mip levels, and invalidation on CPU writes or block transfers.
  *Done 2026-10-19: the authoritative GE decoder now handles every PSP direct, indexed, and DXT texture format across up to eight mip levels, including swizzling, aligned buffer widths, and shared/per-level CLUT rules. D3D12 uses canonical texture and sampler keys, immutable content-versioned resources, decoded RGBA8 mip uploads, per-frame descriptor reuse, bounded LRU eviction, quick/full content verification, and overlap invalidation for CPU, DMA, and block-transfer writes. Focused format/key/range tests, default and D3D12 builds, Make/shader checks, strict MinGW, hardware/WARP boots, graceful cache diagnostics, and a 1,200-frame hardware stress pass (F-068).*
- [x] **T-4.9 P0** Framebuffer cache and VRAM aliasing: render-to-texture, copies on format or stride changes, `sceGeEdram` CPU reads with lazy readback, and block transfer (`TRXKICK`) emulation.
  *Done 2026-10-19: D3D12 now owns serial-protected persistent color/depth targets, synchronized format/stride reinterpretation, direct render-to-texture aliases with feedback snapshots, and cached-target presentation. Shared gated VRAM hooks lazily materialize GPU-newer color data before CPU/DMA/MPEG access; compatible `TRXKICK` rectangles use image copies with a synchronized CPU mirror. Focused identity/conversion/alias/transfer tests, default/D3D12 builds, Make/shader and strict MinGW checks, hardware/WARP boots, safe readback, and an exact 1,200-frame hardware stress pass (F-069).*
- [x] **T-4.10 P0** Depth (16-bit range and `minz/maxz`), stencil-as-alpha, alpha/color test, color doubling, fog, texture function modes and dithering in HLSL.
  *Done 2026-10-19: the shared GE now implements masked color tests plus exact PSP stencil-as-framebuffer-alpha comparisons, fail/depth-fail/pass operations, format quantization, write masks, and destination-alpha preservation. Every D3D12 batch captures a canonical 112-byte/28-DWORD shader block for the existing D16 depth path, alpha/color tests, texture functions, doubling, fog, aliases, dithering, and stencil state. HLSL adds color test and signed 4×4 dithering and safely emits always-pass zero/replace stencil updates; destination-dependent stencil operations and exact post-blend dithering join T-4.11's programmable destination path. Focused raster/state tests, strict builds, hardware/WARP boots, safe readback, and byte-identical reference output pass (F-070).*
- [x] **T-4.11 P1** Destination-aware fragment path: all GE blend equations (including absdiff and fixed colors), logic ops, stencil fail/depth-fail and destination-dependent operations, plus exact post-blend dithering.
  *Done 2026-10-19: the software oracle and destination-aware HLSL now implement exact signed PSP blend arithmetic, every equation/factor and logic operation, complete stencil/depth ordering, post-blend dithering, native-format packing, and per-bit write masks. Per-draw state grows to a canonical 160-byte/40-DWORD block; fixed-function blend/depth approximations are replaced by shader evaluation against ordered BGRA8/R16 destination snapshots at `t2`/`t3`. Typeless D16-compatible depth resources, a dedicated snapshot/bind API, safe null descriptors, and `SR_D3D12_DESTINATION_SAFE=1` validate the path without enabling native replay over the authoritative software framebuffer. Focused raster/state tests, strict builds, hardware/WARP snapshot boots, and the byte-identical saved frame-10 reference pass (F-071).*
- [x] **T-4.12 P1** Bezier/spline patches (CPU tessellation), morph weights and skinning (CPU).
  *Done 2026-10-19: logical vertices now decode up to eight consecutive morph targets and blend positions, UVs, colors, normals, and skin weights before the existing eight-bone CPU transform. `BEZIER` and `SPLINE` use bounded CPU tessellation with indexed controls, exact GE-quantized de Casteljau/de Boor evaluation, fixed-point colors, generated normals/UVs, patch facing, and triangle/line/point topology. Focused morph-order, attribute, topology, pointer, indexing, invalid-input, and 65,536-vertex-cap tests pass alongside default/D3D12 builds, Make/DXC checks, strict MinGW, hardware/WARP boots, and saved-frame hashes (F-072).*
- [x] **T-4.13 P0** Golden-frame harness: capture 50 frames (boot, menu, C1M1 gameplay, a cutscene and the HUD) from the PPSSPP software renderer, then `ppmdiff.py` against the D3D12 output in CI.
  *Done 2026-10-19: a strict dual-index manifest and presentation-timed runtime input script drive isolated PPSSPP/runtime savedata through the title, Continue menu, Chapter 1 storyboard, and C1M1 tutorial/HUD. PPSSPP software output is compared with normalized D3D12 readback under a calibrated delta-64/6,000-pixel gate; a protected self-hosted workflow runs WARP without publishing game assets. Complete WARP and hardware captures pass all 50 frames, while an intentional cutscene/gameplay substitution fails with 71,900 high-delta pixels (F-073).*
- [x] **T-4.14 P1** Debug tooling (install PIX for Windows first): PIX markers per list and draw, a GE state dump on hotkey, and a `SR_GPU_LOG` equivalent for D3D12.
  *Done 2026-10-19: PIX 2603.25 is installed. Deferred D3D12 batches retain immutable GE list/draw context and record nested PIX events; F10 writes a complete decoded/raw GE state file; `SR_GPU_LOG=1` reports flushes, logical draws, presents, and totals. Focused tests and a live WARP/F10 boot pass (F-074).*
### 4c: performance
- [ ] **T-4.15 P1** Async PSO compilation, an `ID3D12PipelineLibrary` disk cache and an ubershader fallback, so there are no first-use hitches.
- [ ] **T-4.16 P2** Decode vertices in the shader from raw GE buffers, batch draws within a list, and cache constant-buffer state.

## Phase 5 — Audio, video, input
- [ ] **T-5.1 P0** SasCore gaps: ADSR (`SetADSR`, `SetADSRmode`, `SetSimpleADSR`, `SetSL`), reverb (`RevType`, `RevParam`, `RevEVOL`, `RevVON`), noise and pause. → F-031
- [ ] **T-5.2 P0** sceAudio `Output2*` (SRC channel). Mic input stubbed to "no device".
  *2026-10-19: `Output2Reserve/OutputBlocking/ChangeLength/Release` done (host mixer channel 8, F-053). Mic input (`sceAudioInput*`) still to do.*
- [ ] **T-5.3 P1** Atrac3+ gaps: `GetInternalErrorInfo`. Confirm looping BGM.
  *2026-10-19: `sceAtracGetBufferInfoForResetting` now returns the fully resident-buffer contract with focused valid/error coverage; internal error reporting and looping-BGM confirmation remain.*
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
