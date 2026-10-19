# WORK DONE — archive

A dated log of finished work, newest first. Each entry lists what was done, what it produced, and the
findings or tasks it touched. Items move here from [TODO.md](TODO.md) when they are ticked off.

---

## 2026-10-19 — Session 2q: D3D12 device and swapchain foundation (T-4.2)
- Added `src/rt/gpu_d3d12/device.cpp` and its C/C++ boundary. SDL3 creates the window and supplies its Win32
  `HWND`; the backend selects a high-performance hardware adapter (or explicit WARP), creates direct/copy queues,
  timeline fences, three frame allocators, and a three-buffer flip-discard BGRA8 swapchain.
- Added a 4,095-entry shader-visible CBV/SRV/UAV ring partitioned by in-flight frame, reusable 256-entry RTV and
  64-entry DSV pools, and a persistently mapped 24 MiB upload ring. Until the HLSL/PSO stages land, D3D12 uploads
  the proven software-GE framebuffer through that ring, so the backend is independently usable and testable.
- Wired `SR_GPU=d3d12` into the GUI, including SDL input, fatal device-error propagation, explicit GDI conflicts,
  a `KZL_ENABLE_D3D12` CMake option, and the fork Makefile's SDL3/Vulkan/D3D12 build.
- Validation: both normal and D3D12 clang-cl targets build and their focused CTests pass 1/1; `device.cpp` also
  compiles warning-free with MinGW g++. Hardware and WARP smoke boots pass, a 10-frame run wraps all three frame
  slots, and a hardware run reaches frame 1,200 with the unchanged language-screen SHA-256
  `B47E272E...833D1C49`. The host lacks the optional Windows Graphics Tools debug layer, and requesting it fails
  explicitly with `DXGI_ERROR_SDK_COMPONENT_MISSING`. T-4.2 is complete. → F-062

## 2026-10-19 — Session 2p: interchangeable GE backend interface (T-4.1)
- Promoted the draw-only `GeGpuHooks` seam into a named `GeBackend` descriptor covering initialization, direct
  target presentation, shutdown, primitives, synchronization, CPU invalidation, and block transfer. `ge.c` now
  knows only that descriptor; the reference software rasterizer remains the null-backend path.
- Reworked the existing SDL3/Vulkan renderer to export a `vk` descriptor instead of registering itself. The GUI
  selects `SR_GPU=sw|vk|d3d12`, activates descriptors generically, and routes direct framebuffer presentation and
  shutdown through them. Invalid names, unsupported compiled backends, initialization failures, and conflicting
  `SR_GPU=vk`/`SR_VIDEO=gdi` settings are explicit errors; legacy variables remain compatible.
- Validation: both clang-cl targets build and focused CTest passes 1/1, including a fake-backend registration and
  VRAM-invalidation regression. The Vulkan source passes a GCC C11 syntax check against current public Vulkan
  headers. Selector failure cases return exit 2, `SR_GPU=sw` renders through GDI, and strict headless frame 1,200
  remains bit-identical (SHA-256 `B47E272E...833D1C49`). T-4.1 is complete. → F-061

## 2026-10-19 — Session 2o: executed function-boundary audit (T-2.7)
- Extended the reproducible PPSSPP v1.20.4 patch with `PSPRECOMP_CALLTRACE`, a compact interpreter hook that records
  each unique executed `jal`/`jalr` source and runtime target. Unlike the full CPU trace, it can cover a long boot
  without producing hundreds of megabytes of register deltas.
- Added `tools/kzl/ppsspp_calls.py` for bounded deterministic captures and `tools/kzl/calltargets.py` for strict
  comparison with the relocated analyzer inventory. The audit recognizes `[[jal_next]]` targets as intentional
  non-functions, rejects malformed traces, writes a hash-stamped report, and exits nonzero on an unknown target.
- Validation: the parser/classifier unit tests pass, the patched PPSSPPHeadless builds, and the distributable patch
  passes plain `git apply --check` on a clean v1.20.4 worktree. A 90-second capture produced 12,399 unique edges and
  4,553 in-module targets, with zero misses against the effective 42,600-function inventory. T-2.7 is complete.
  → F-060

## 2026-10-19 — Session 2n: trace-free standalone loader (T-3.1)
- Added `kzl.exe --boot` for the normal runtime path. It maps the pre-relocated `kzl_image.bin`, reserves the
  BOOT.BIN/kernel UID history, supplies `"modulename"`, enables scheduling, and enters the module's own constructor
  and startup path without reading a PPSSPP trace.
- The scheduler now creates `module_start` through the existing PPSSPP-compatible thread reset path with UID 0x11C,
  a 0x400-byte high stack at 0x09FFFC00, k0 0x09FFFF00, sp 0x09FFFEB0, a0/a1 11/0x09FFFEF0, and the kernel return
  trampoline at 0x08000030. Seeded differential mode still adopts and validates the oracle-provided thread.
- Validation: both targets built and focused CTest passed 1/1. A strict trace-free run reached SELECT YOUR LANGUAGE
  at frame 1,200 with no unimplemented NID and showed `user_main` as UID 0x11D. Legacy `--image` mode remains
  instruction-identical to PPSSPP for its complete 71-step module-start trace. T-3.1 is complete. → F-059

## 2026-10-19 — Session 2m: MPEG intro completion and PPSSPP oracle (T-3.2)
- Fork sceMpeg: fixed PPSSPP's six-byte PSMF timestamp layout, capped stream feeding at the declared packet count,
  and moved packet consumption from `sceMpegGetAvcAu` to timestamp-proportional AVC decode. MPEG-2 pack SCR tracking
  now recognizes when the decoder already holds the video tail, so reordered frames continue after the ring drains.
- Added a synthetic three-frame/10-packet HLE regression covering the corrected timestamps, proportional demux,
  ring-empty decoder tail, final no-data AU, and teardown. The real 11,573,248-byte intro reports 5,650 stream packets,
  timestamps 90,000..7,402,305, and an 81.248 s duration.
- Extended the reproducible PPSSPP v1.20.4 patch with `PSPRECOMP_PADSCRIPT`; its clean `git apply --check` passes and
  the rebuilt oracle accepts the same vblank-based input script as the runtime.
- Validation: both runtime targets built and focused CTest passed 1/1 with the KZL ISO. Patched PPSSPP and the strict
  runtime both made 2,435 successful AVC decodes followed by one no-data AU and the same teardown order; the runtime
  resumed presentation without an unimplemented NID. T-3.2 is complete. → F-058

## 2026-10-19 — Session 2l: LocalAppData VFS completion (T-3.3)
- Fork IoFileMgr: writable storage now defaults to `%LOCALAPPDATA%\KZLRecomp\ms0`; `fatms0:` and `cache:` alias that
  same hierarchy, while `SR_FSDIR` remains an explicit test/developer override. A missing `LOCALAPPDATA` is reported
  instead of silently falling back to a repository-relative directory. ISO-backed `disc0:` behavior is unchanged.
- Extended `kzl_hle_smoke` to write `cache:CHAPTER5.BIN`, stat it through `fatms0:`, read it through `ms0:`, and verify
  the exact physical location and contents under the default root. Existing override-path and real-ISO coverage remains.
- Validation: `kzl_hle_tests` and `kzl_driver` built; focused CTest passed 1/1 with the KZL ISO. A strict turbo scheduled
  boot with `SR_FSDIR` unset reached and captured frame 1,200 without an unimplemented NID. T-3.3 is complete. → F-057

## 2026-10-19 — Session 2k: deterministic offline networking (T-3.7)
- Fork: added `src/rt/net.c` and registered all 69 networking imports, both imported sceWlan calls, and the existing
  `sceWlanDevIsPowerOn` entry. Lifecycle calls are local no-ops; stable MAC/OpenPSID and numeric IPv4 conversion work;
  Inet, resolver, infrastructure and ad-hoc operations return deterministic offline errors without host networking.
- Extended `kzl_hle_smoke` to invoke every one of the 71 imported networking NIDs and verify WLAN-off/disconnected
  errors, Inet `ENETDOWN`, resolver failure, stable identity output and IPv4 parsing. A mechanical import audit reports
  71/71 registered. → F-056
- Fixed the clang-cl CMake path to use the adjacent `llvm-lib.exe`; WinLibs `ar.exe` on PATH cannot consume CMake's
  MSVC librarian flags.
- Validation: focused CTest 1/1 passed with the KZL ISO, and `kzl_driver` built. A strict paced scripted run selected
  PLAY A GAME → MULTIPLAYER → COMBAT ZONE - ADHOC → JOIN GAME, exercised ad-hoc init/connect/teardown, and rendered
  "NETWORK ERROR OCCURRED, WLAN SWITCH HAS BEEN TURNED OFF" with no unimplemented NID. T-3.7 is complete.

## 2026-10-19 — Session 2j: scheduled asynchronous file I/O (T-3.5)
- Fork scheduler: added reusable HLE helper fibers, with real thread objects, typed UIDs, PSP stack allocation,
  priorities and ThreadMan visibility. IoFileMgr uses one `SceIoAsync` helper per participating descriptor.
- Fork IoFileMgr: async open/read/seek/close now have pending, ready, consumed and close-pending states; reject overlap
  with `ASYNC_BUSY`; distinguish pending polls from waits; return signed 64-bit results; and delay completion using
  PPSSPP's timing estimates. Async close releases the fd only when its result is consumed, and failed async opens use a
  temporary fd carrying the open error. `sceIoChangeAsyncPriority` controls default and active helper priorities. → F-055
- Extended `kzl_hle_smoke` with a scheduler-driven async sequence covering helper-thread enumeration/status, pending
  polls, blocking waits, busy/no-async/bad-fd errors, read/seek data, deferred close, and failed-open cleanup.
- Validation: CTest 1/1 passed with the KZL ISO; the allocator differential passed 320,000 operations/80 seeds with
  0 mismatches; and the clang-cl driver build passed. A strict paced run created one priority-0x24 `SceIoAsync` helper,
  reached vblank 3,600 without an unimplemented NID, and rendered PLAY A GAME. T-3.5 is complete.

## 2026-10-19 — Session 2i: ThreadMan and directory I/O completion (T-3.4, T-3.5 partial)
- Fork ThreadMan: added typed UID tracking for threads, semaphores, event flags, FPLs and callbacks; scheduler-owned
  thread metadata and exit status; PPSSPP-compatible `sceKernelReferThreadStatus`, `sceKernelGetThreadExitStatus`,
  `sceKernelGetThreadmanIdList` (including state filters), and `sceKernelSysClock2USec`. T-3.4 is complete. → F-054
- Fork IoFileMgr/ISO: added ISO9660 lookup/list APIs; host and ISO `sceIoDopen/Dread/Dclose`; `sceIoRemove`,
  `sceIoRmdir`, and host-backed `sceIoGetstat`. Writable-device paths retain hierarchy, `fatms0:`/`cache:` alias
  `ms0:`, and reads retain compatibility with the prior flat mapping. Reserved fd 0–2 so the first file write is not
  mistaken for stdout. Async worker-thread/delay modeling remains, so T-3.5 stays open. → F-054
- Root CMake now reuses one runtime source list for `kzl_driver` and the new `kzl_hle_tests` target. The focused smoke
  test directly invokes the HLE NIDs and covers ThreadMan ABI/errors/lists, clock conversion, host directory and removal
  behavior, invalid handles, and real KZL ISO enumeration.
- Validation: CTest 1/1 passed with `PSP_ISO`; the allocator differential passed 320,000 operations/80 seeds with
  0 mismatches; the full clang-cl `kzl_driver` build passed. A strict 3,600-vblank headless run had no unimplemented NID
  and captured SELECT YOUR LANGUAGE, MAIN MENU, and PLAY A GAME, preserving F-053.

## 2026-10-19 — Session 2h: GE display lists, callbacks, headless main menu (T-3.6, T-3.9, T-3.10)
- Fork: new `src/rt/gelist.c`, a port of PPSSPP's display-list manager (`GPUCommon`: enqueue, stall, every
  SIGNAL behaviour, FINISH/END, Break, Continue, ListSync, DrawSync) and its GE interrupt handler, with all sceGe
  calls KZL imports. `ge.c` now executes single commands (`ge_execute_op`, `ge_list_begin/end`); list control flow
  moved out of it. KZL's libgu signal path (handler → `SetEventFlag(SceGuSignal)` → resume → finish handler)
  matches PPSSPP's log. → F-051
- Fork: new `src/rt/intr.c` (PPSSPP's sub-interrupt table) and `sched_run_interrupt()`. Vblank and GE handlers
  run through it, and an interrupt raised inside another one is delivered after it returns. Vblank sub-handlers now
  get a0 = sub-interrupt number, as in PPSSPP.
- Fork: new `src/rt/callback.c`, PPSSPP's kernel callbacks (create/delete/notify/cancel/count/check, run on the
  owning thread with the 128-byte save area) and the scePower callback slots. The scheduler runs callbacks in
  every ...CB wait (`sceKernelDelayThreadCB` added; Sleep/WaitSema/WaitEventFlag/WaitThreadEnd/IoWaitAsync CB
  variants now process callbacks). → F-052
- Fork `hle.c`: `sceIoDevctl` ported (UMD, memory stick, fatms0, callback notification), `sceIoChangeAsyncPriority`,
  `sceRtcGetCurrentTick` (PPSSPP epoch) and `sceRtcGetTime_t`, `sceImpose{Get,Set}LanguageMode`, `sceAudioOutput2*`,
  `sceCtrlPeekBufferPositive`, `sceCtrlSetSamplingCycle`, UMD activate/deactivate/prohibit with the UMD callback,
  Dcache/GPI, `sceMpegAvcDecodeMode`. `SR_NIDLOG` now records the thread and flushes every line.
- Fixed two sal063 bugs: `sceIoLseekAsync` read its offset from the wrong register (every PSP.DAT read came from
  offset 0, then a NULL virtual call at 0x08837744), and `sceKernelSetCompilerVersion` overwrote the SDK version.
  The wrongly registered `sceRtcGetTick` (it takes `pspTime*, u64*`) was removed. → F-052
- New `tools/kzl/hleseq.py`: aligns PPSSPP's debug-log HLE sequence with ours (`SR_NIDLOG`). It found the
  memory-stick and Lseek divergences.
- `SR_DLDUMP=<vblank>`: dumps a frame's executed GE commands to `gedump_f<vblank>.txt`.
- Result: strict mode boots to SELECT YOUR LANGUAGE and, with a pad script, to the PLAY A GAME main menu, with no
  unimplemented NID. `module_start` still matches PPSSPP for 71 steps, and the memory probe still matches F-050. → F-053

## 2026-10-19 — Session 2g: PPSSPP's memory allocator in the runtime (T-3.13)
- Fork: new `src/rt/kmem.c`, a literal C port of PPSSPP's `BlockAllocator`, with kernel, volatile and user partitions.
  User memory starts with `usersystemlib` (16 KB), then the loaded module. `sceKernelAllocPartitionMemory` (all five
  placement types), `Free`, `GetBlockHeadAddr`, `MaxFreeMemSize` and `TotalFreeMemSize` now follow PPSSPP. The UID is
  taken only when an allocation succeeds. All eight FPL calls are implemented on the allocator. The bump allocator in
  `hle.c` is gone.
- Fork: thread stacks come from the user partition (from the top, or low with attr 0x00400000). A started thread gets
  PPSSPP's start state: register reset, 0xFF stack fill, k0 block, argument copy, 64-byte return stub. `DeleteThread`,
  `ExitDeleteThread` and `TerminateDeleteThread` free the stack and the thread slot. The entry thread takes its UID
  (0x11C) and stack from the seed's k0 block and is deleted when `module_start` returns. The vblank and GE/mpeg callback
  stacks moved out of user RAM into the kernel partition.
- `tools/tests/test_kmem_blockalloc.py` (fork) builds PPSSPP's `BlockAllocator.cpp` next to `kmem.c` and compares them on
  320,000 random operations: 0 mismatches, and 4 of 4 injected bugs caught.
- KZL's memory probe now matches PPSSPP: same layout, the same 25 DummyHeap results, and `GameHeap` 0xFBF800 at
  0x08EB8800. `module_start` still matches for 71 steps. Strict mode now stops at `sceRtcGetCurrentTick` instead of
  `sceKernelCreateFpl`. → F-050
- Found that UIDs fall one behind PPSSPP after `user_main`, because BOOT.BIN's unload creates a thread in PPSSPP (new
  T-3.14). Vpl is not imported by KZL. → F-050

## 2026-10-19 — Session 2f: first recompiled-vs-PPSSPP comparison (T-3.1 started)
- Trace header in the PPSSPP patch: `# init` (all registers), `# kernel next_uid`, `# mem` (top 4 KB of user RAM).
  The post-HLE `0xDEADBEEF` filling stays on, since sal063 reproduces it. The patch now touches 3 files.
- Fork: the driver reads the full header; `sr_set_next_uid`; `tracediff.py` accepts any word against a syscall in
  stub delay slots; analyzer and codegen find per-library `.sceStub.text.<lib>` sections (300 import stubs were missing).
- `kzl_driver` CMake target builds `kzl.exe` (runtime without SDL3/Vulkan, 0 link errors); `gen.py` writes the
  relocated image. `module_start` runs **identically to PPSSPP for all 71 steps**. → F-049
- Scheduler mode reaches the first missing HLE call (`sceKernelCreateFpl`). Found that sal063's bump allocator
  cannot survive KZL's memory probe, so a `BlockAllocator` port comes first (new T-3.13). → F-049

## 2026-10-19 — Session 2e: PPSSPP trace oracle (T-2.11, oracle side)
- [tools/ppsspp/psprecomp-trace.patch](tools/ppsspp/psprecomp-trace.patch) for PPSSPP v1.20.4: PPSSPPHeadless's interpreter
  writes the psp-recomp trace format. While tracing it forces the checked interpreter loop, turns off function
  replacements and the post-HLE `0xDEADBEEF` filling, and writes `<trace>.done` when finished. Applies cleanly to
  a fresh v1.20.4 checkout; build steps in [tools/ppsspp/README.md](tools/ppsspp/README.md).
- [tools/kzl/ppsspp_trace.py](tools/kzl/ppsspp_trace.py): records a KZL trace; 5M steps from `module_start` in 3 s.
  `tracediff.py` accepts the output.
- Read off the thread start state, the `module_start` entry registers, and the coverage problem of the first
  5M steps (one sort loop). → F-048

## 2026-10-19 — Session 2d: PPSSPP reference (T-0.5)
- Installed PPSSPP 1.20.4 desktop from the official release zip (SHA-256 matched GitHub's digest) to
  `D:\Tools\PPSSPP-1.20.4`.
- Built PPSSPPHeadless from the v1.20.4 tag (`D:\Github\ppsspp`, MSBuild Release x64, 1 min 12 s, 0 errors).
- Booted KZL in both (desktop 60 s with a debug log, headless 40 s on the interpreter with the software renderer).
  Confirmed the start arguments and load base, and that the game reads only PSP.DAT. → F-047
- [tools/kzl/hlesummary.py](tools/kzl/hlesummary.py) and [research/ppsspp_boot_hle_60s.txt](research/ppsspp_boot_hle_60s.txt):
  79 HLE functions on the boot path, 22 without a sal063 handler. Logs are in `build/kzl/ref/` (not committed).

## 2026-10-19 — Session 2c: clang-cl build (T-0.1, T-2.9 started)
- clang-cl 19.1.5 installed in the VS Build Tools. All 231 TUs compile with clang-cl `-O2 -W3`.
- Codegen cleanups in the fork (`kzl` branch): a `j` to the function's own entry is a yielding loop instead of a self
  tail call (F-046); FPU compares fold their constant condition bits (13,489 warnings gone); split mode keeps the
  static inline helpers in the shared header. Result: 0 warnings.
- [CMakeLists.txt](CMakeLists.txt) and [CMakePresets.json](CMakePresets.json): preset `clang-cl` (Ninja, Release)
  builds `kzl_game.lib` in 49 s. VS Code CMake Tools loads the MSVC environment from the preset. → T-2.9

## 2026-10-19 — Session 2b: sal063 fork, codegen complete (T-0.3, T-2.1 to T-2.6, T-2.8, T-2.13)
- Created the private mirror `Tzeentchnet/psp-recomp` (upstream history on `main`, our work on `kzl`) and added it as
  the submodule `external/psp-recomp`. → T-0.3
- Moved `codegen_ext.py` and its tests into the fork and wired them into `codegen.py`: new encodings, `bv*` branches,
  switch tables and computed gotos from the hint files, `jal .+8`, and reading the jump register before the delay
  slot for every `jr`/`jalr`. → T-2.1 to T-2.6, T-2.13, F-019
- Switch cases exposed `vasin` and `vnop`/`vflush`. Ported PPSSPP's `vfpu_asin` to `src/rt/vfpu_asin.c` and checked it
  bit for bit against PPSSPP's own code on every input in [-1, 1]. → F-016
- Fixed the analyzer's stale-`lui` heuristic: 342 bogus function entries gone (6 had produced C that did not compile).
  → F-015
- `codegen.py --split` and [tools/kzl/gen.py](tools/kzl/gen.py): 42,300/42,300 functions, **0 trapping stubs**, 230 TUs.
  All pass `gcc -fsyntax-only -Wall` cleanly; a full gcc `-O2` compile takes 2 min 49 s on 16 threads. → T-2.8, T-2.9
- Noted that the generated code needs GNU C, so clang-cl is required on Windows. → F-045
- Fork commit: `01494dc` on `kzl`.

## 2026-10-19 — Session 2: phase 1 tools, BOOT.BIN, PSP.DAT, codegen extensions

**Phase 1 (T-1.1, T-1.2, T-1.6, T-1.7 done)**
- [tools/kzl/iso9660.py](tools/kzl/iso9660.py): read-only ISO reader shared by the KZL tools.
- [tools/kzl/extract.py](tools/kzl/extract.py): checks the ISO size and SHA-1, extracts the 7 files the build needs
  plus the PSP.DAT TOC to `build/kzl/disc/`, and checks each file's SHA-1. → T-1.1
- [config/kzl.toml](config/kzl.toml): disc and file hashes, load base, entry, start-thread params, boot argv,
  PSP.DAT counts. → T-1.2
- [tools/kzl/mipsdis.py](tools/kzl/mipsdis.py): an Allegrex disassembler with import-stub names, string xrefs and
  call-site listings. [tools/kzl/nidnames.py](tools/kzl/nidnames.py) builds [research/nid_names.tsv](research/nid_names.tsv)
  (1,759 NIDs from PPSSPP's HLE tables; all 300 KZL imports are named).
- BOOT.BIN reversed: load path, retry thread, and `module_start(11, "modulename")`; `-patch_failed` is only passed
  after a failed update load. → T-1.6, F-004
- [tools/kzl/pspdat.py](tools/kzl/pspdat.py): PSP.DAT TOC fully decoded (5,005 records, depth-first tree with child
  pointers). The tree validates, and 165 files are duplicated up to 40 times for seek locality. → T-1.7, F-020

**Phase 2 groundwork (T-2.1 to T-2.6: logic done, integration pending as T-2.13)**
- Counted the exact trapping sub-ops in KZL (F-016) and wrote `codegen_ext.py` (now [external/psp-recomp/tools/codegen_ext.py](external/psp-recomp/tools/codegen_ext.py)):
  `bitrev`, `wsbw`, `cache`, `vf2i*`, `vi2f`, `vuc2i/vc2i/vus2i/vs2i`, `vfad`, `vsgn`, `vmscl`, `bv*` conditions, a
  jump-table `switch` emitter and a `jal .+8` emitter. All 193 affected instructions in `.text` decode.
- `external/psp-recomp/tools/tests/test_codegen_ext.py`: emits C, compiles it with gcc against a
  stand-in CpuState and runs 195 cases against Python models of PPSSPP's interpreter. Mutation check: injected bugs in
  `bv*`, `vf2in` rounding and `vus2i` are each caught.
- [tools/kzl/jumptab.py](tools/kzl/jumptab.py): 240 of 243 computed `jr` recovered as switch tables (4,480 cases), with
  a layout cross-check showing no over- or under-counted tables. → F-018
- Found the native-call thunk with a `jal .+8` get-PC trick and `jr t4; addiu t4, t4, 8` ladders, which sal063
  would mistranslate; recorded in [config/kzl_overrides.toml](config/kzl_overrides.toml). → F-019
- Noted sal063 runtime limits at KZL scale (65,536-slot dispatch hash). → F-043

**Toolchain:** MSVC 14.44, Windows SDK 10.0.26100 (dxc) and gcc 16.2 are now installed; clang-cl and PIX are not. → F-041

**Not done:** T-0.3 (bringing sal063 into the repo) was held back for a decision, so nothing is wired into the codegen
yet and the 77 trapping stubs are not regenerated. No PPSSPP install (T-0.5).

## 2026-10-19 — Repository created (T-0.2)
- Ran `git init` (branch `main`) and added a `.gitignore` that excludes the ISO, PRX/BIN/DAT/PBP files, `CHAPTER5.BIN`, generated `*_recomp*.c` and build output.
- Created the private GitHub repo `Tzeentchnet/KillzoneLiberation-Recomp` and pushed the initial commit.

## 2026-10-19 — Session 1: survey and plan

**Disc survey**
- Parsed the ISO9660 file table of `Killzone_Liberation_v1.20_US.ISO` and hashed the image and its key files. → F-001, F-002
- Found that `KZL.PRX` (the game) and `KZL.PRX.100` are **plaintext PRX ELFs**, and that `BOOT.BIN` is a plaintext
  bootloader ELF. `mpeg.prx` is `~SCE`-encrypted. → F-003, F-004, F-032
- Parsed both PARAM.SFO files and UMD_DATA.BIN.

**KZL.PRX static survey** (`tools/survey/prx.py` → [research/kzl_prx_survey.txt](research/kzl_prx_survey.txt))
- Listed the 70 sections, the program headers and the module info (`Guerrilla`). Resolved the exports:
  `module_start` is at offset 0, and the start-thread params are prio 0x20, stack 0x400. → F-010
- Counted the instruction mix: 1.45M instructions, VFPU and FPU usage, and 243 computed `jr`. → F-011, F-017
- From strings, identified Lua 4.0, Havok Physics, the SVML browser UI and the Chapter 5 DLC hooks. → F-012, F-013, F-014, F-021
- Listed the 300 imports from 34 libraries. → F-030

**Reference framework trial** (sal063 `da17b0e`, cloned to a scratch folder and not vendored yet)
- `analyze.py` found **42,641 functions** (18 s). → F-015
- `codegen.py` translated **42,641 of 42,641 functions with 77 trapping stubs** (26 s) and wrote one 237 MB C file. The stubs fall into 7 opcode classes. → F-016
  Stub list: [research/codegen_trapping_stubs.txt](research/codegen_trapping_stubs.txt)
- `imports.py` produced the NID map. → [research/kzl_imports.toml](research/kzl_imports.toml)
- Cross-checked the imports against the HLE handlers registered in sal063: **159 of 300 are implemented**. → F-031
  Report: [research/hle_coverage_vs_sal063.txt](research/hle_coverage_vs_sal063.txt)
- Checked how sal063 handles dispatch: jump-table targets are not recovered. → F-017

**PSP.DAT**
- Parsed the header and name pool: 3,987 entries and 1,292 unique names, with counts by file type. The TOC record layout is a hypothesis. → F-020

**Documents created**
- [PLAN.md](PLAN.md): architecture, decisions D1–D8, phases 0–8 with exit criteria and estimates, the D3D12 design, and risks.
- [TODO.md](TODO.md): about 75 tasks with IDs, priorities and links to findings.
- [FINDINGS.md](FINDINGS.md): findings F-001 to F-042.
- [tools/survey/](tools/survey/): `isols.py` (lists and dumps ISO files), `inspect.py` (header and SFO dumps),
  `prx.py` (PRX survey), `hlecov.py` (HLE coverage against a runtime tree).

**Not done or deferred:** no git repo has been created yet (T-0.2). sal063 is not added as a submodule yet (T-0.3).
No compiler is installed, so nothing was built (T-0.1). The 237 MB trial C output was left in scratch and is not part of the project.
