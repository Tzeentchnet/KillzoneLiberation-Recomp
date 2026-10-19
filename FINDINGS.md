# FINDINGS — Killzone: Liberation (UCUS-98646 v1.20) → Windows / Direct3D 12 recomp

Things learned about the target that shape the plan. Each entry gives the evidence,
how confident we are, and what it means for the work. IDs are stable, so TODO.md
and WORK_DONE.md can cite them.

Confidence levels: **Confirmed** (measured directly) · **Likely** (strong inference) · **Hypothesis** (still to verify).

Raw data lives in [research/](research/). The scripts that produced it are in [tools/survey/](tools/survey/).

---

## A. Disc image and provenance

### F-001 Disc identity — Confirmed
- `Killzone_Liberation_v1.20_US.ISO`, 568,498,176 bytes, SHA-1 `5bc4fc8cd8d72c9c2e7c1c03a4325a29bed6e69a`.
- PARAM.SFO: `DISC_ID=UCUS98646`, `DISC_VERSION=1.20`, `PSP_SYSTEM_VER=2.80`, `CATEGORY=UG`, title "Killzone®: Liberation v1.20".
- UMD_DATA.BIN: `UCUS-98646|7C55E90A5958C876|0001|G`.
- **Impact:** every address in these docs refers to this exact build. Record the hash in the build config and refuse to run on a mismatch.

### F-002 Disc layout — Confirmed
| Path | Size | What it is |
|---|---|---|
| `PSP_GAME/SYSDIR/EBOOT.BIN` | 78 KB | `~PSP`-wrapped module named `bootloader` (comp attr 0x2) |
| `PSP_GAME/SYSDIR/BOOT.BIN` | 78 KB | **Plaintext** absolute ELF of that bootloader (entry `0x09F001F4`) |
| `PSP_GAME/USRDIR/KZL.PRX` | 8.5 MB | **The game.** Plaintext relocatable PRX (ELF type 0xFFA0) |
| `PSP_GAME/USRDIR/KZL.PRX.100` | 8.1 MB | Plaintext PRX, almost certainly the v1.00 game module |
| `PSP_GAME/USRDIR/BINPSP/mpeg.prx` | 20 KB | `~SCE`-encrypted Sony libmpeg module |
| `PSP_GAME/USRDIR/PSP.DAT` | 522 MB | Guerrilla asset archive (see F-020) |
| `PSP_GAME/USRDIR/SHARED.DAT` | 8 MB | A `PBP` image: the Game Sharing payload sent to another PSP |
| `PSP_GAME/SYSDIR/UPDATE/*` | 15 MB | Firmware 2.80 updater. Ignore it |

### F-003 The game executable is not encrypted — Confirmed
`KZL.PRX` and `KZL.PRX.100` are plain ELF files with full section headers, so no PRX decryption step is needed.
That is unusual for a retail disc. The community-fixed v1.20 build (2022) shipped a decrypted 1.2 module, so this
ISO may be that build (see the speedrun.com KZL guide).
- **Impact:** the recompiler can read `KZL.PRX` directly. Before any team relies on the image, verify it against a
  known-good dump (Redump) so everyone targets the same bytes.

### F-004 The bootloader can be skipped; it passes a placeholder argv — Confirmed
BOOT.BIN is not thin: it imports sceHttp/sceSsl/sceNet\*, 15 sceUtility functions, sceGe and sceDisplay, plus an
inflate/Adler-32 routine. It checks for a downloaded update, loads it with `sceKernelLoadModuleDNAS` (with a key blob at
0x09F0DF2F) and otherwise loads the disc module. From its disassembly (`tools/kzl/mipsdis.py`):
- `sceKernelLoadModule("disc0:/PSP_GAME/USRDIR/KZL.PRX", 0, NULL)` at 0x09F0193C, run from a thread (prio 0x6F,
  stack 0x800) that retries every 3 s on failure. The path comes from `0x09F00678("KZL.PRX")` plus a directory prefix.
- `sceKernelStartModule(modid, args, argp, &status, NULL)` at 0x09F01C3C. `argp` is the literal placeholder
  `"modulename"` (`args = 11`). Only when an update was present **and** failed to load does it pass
  `"modulename\0-patch_failed\0"` (`args = 25`); KZL.PRX checks this through `DidPatchFailToLoad`.
- BOOT.BIN's own options `-nopatch` and `-patch_binary` (strings at 0x09F026CC/0x09F02704) only steer the update step.
- **Impact:** the runtime loads KZL.PRX directly and calls `module_start(11, "modulename")`. Recorded in
  [config/kzl.toml](config/kzl.toml) `[boot]`. The update servers are gone (F-022), so the patch path never applies.

---

## B. Code shape of KZL.PRX

### F-010 Module facts — Confirmed
- Module name `Guerrilla`, attr 0, version 1.1, built against SDK 2.80.
- Two PT_LOAD segments. Text and rodata are 0x67BAC0 bytes (R+X). Data and bss are 0x28C50 in memory (0xBAF8 in the file).
- `.text` is 0x58AA58 bytes = **1,453,294 MIPS instructions (5.54 MiB)**.
- `.symtab` is empty (0x10 bytes), so the module is **stripped**. Strings show source paths such as `../../source/SVBrowser.cpp`.
- Sections `.cplinit`, `.linkonce.d`, `.ctors`/`.dtors` and `.eh_frame` point to C++ built with **SN Systems ProDG (GCC-based)** — Likely.
- Exports: the `syslib` table only. `module_start` is at **module offset 0x0**, `module_stop` at 0x3D0.
  The start thread params are `{count 3, prio 0x20, stack 0x400, attr 0x80000000}`.
- **Impact:** load base 0x08804000 gives `GAME_ENTRY=0x08804000`.

### F-011 Instruction mix — Confirmed
| Class | Count | % |
|---|---|---|
| FPU (COP1) | 71,488 | 4.92 |
| `jal` direct calls | 69,849 | 4.81 |
| `jr` | 43,576 | 3.00 (43,033 are `jr $ra`; **243 are computed jumps**) |
| `jalr` indirect calls (C++ virtual calls) | 16,331 | 1.12 |
| VFPU load/store | 15,440 | 1.06 |
| VFPU ALU | 5,550 | 0.38 |
| VFPU COP2 moves/branches | 1,618 | 0.11 |
- **Impact:** the VFPU is used moderately (about 22.6k instructions) and the scalar FPU heavily (Havok, F-013).
  Floating-point accuracy matters more than VFPU coverage.

### F-012 Embedded Lua 4.0 — Confirmed
The strings `Lua 4.0`, `luabin` and `lua_getinfo` are present, and PSP.DAT holds **582 `.luabin` (compiled Lua bytecode)**
files plus 12 `.lua` files: level scripts, unlockables, cutscenes.
- **Impact:** game logic in Lua runs inside the recompiled VM and needs no special handling. Later, it is a clean
  hook point for mods and debugging.

### F-013 Havok Physics is linked statically — Confirmed
There are about 320 `hk`/`HK_` strings: `hkWorld::getPenetrations`, `HK_SHAPE_TRI_PATCH`, `Havok Prime`, and evaluation-key messages.
- **Impact:** physics is very sensitive to float behavior. The PSP FPU is single precision with flush-to-zero.
  The host needs SSE with FTZ/DAZ on and `-ffp-contract=off`, and must not let compiler fast-math reorder
  operations (otherwise ragdolls and explosions drift from the original).

### F-014 The front end is an SVML "browser" — Confirmed
The UI runs on Sony's SVO/SVML markup. `SVBrowser.cpp`, `*TagModule.cpp` (Form, TextInput, Grid, URLList…)
and **56 `.jsp` pages** in PSP.DAT (`svo/svml/kzpsp/…`: mainmenu, chapterselect, adhoc lobby, `debugoptions.jsp`).
- **Impact:** menus are rendered by game code, so no special HLE work is needed. Check that local pages never go
  through `sceHttp` (T-3.12). `debugoptions.jsp` is a debug menu that could be unlocked — worth investigating (T-6.6).

### F-015 Function inventory with the sal063 analyzer — Confirmed
`tools/analyze.py --base=0x08804000` finds **42,641 functions** in 18 s. With no symbols, recall cannot be measured.
- **Update (2026-10-19): 42,300 after a fix.** The analyzer's `lui`/`addiu` pointer heuristic never forgot a
  register's `lui` value when the register was overwritten, so a later unrelated `addiu` "computed" a code address.
  That produced **342 bogus entries**, all a 64 KB boundary plus a small offset (0x08810004, 0x08940004, ...). 48 sat in
  delay slots, and 6 of those made the generated C jump to labels that do not exist. Fixed in the fork; the fix also
  surfaced 3 real entries (two `b .` halt loops and the `jal .+8` target, which the codegen drops again).
- **Impact:** this inventory is good enough to start from. Check it against PPSSPP runtime traces (T-2.7).

### F-016 sal063 codegen runs on KZL.PRX today — Confirmed
`tools/codegen.py` emitted **42,641 of 42,641 functions, 77 of them trapping stubs**, in 26 s.
The output is **237 MB of C, about 3.0M lines, in one file**.
Unsupported encodings ([research/codegen_trapping_stubs.txt](research/codegen_trapping_stubs.txt)):
| Codegen error | Functions | Likely instruction (check against PPSSPP's MIPSTables) |
|---|---|---|
| `cop2 sub 8` | 25 | `bvf`/`bvt`/`bvfl`/`bvtl`: branch on VFPU condition code |
| `VFPU9 op 0x06` | 24 | `vfad` (funnel add) |
| `VFPU4 jump 0x01` | 9 | VFPU7 group: `vf2h`/`vh2f`/`vs2i`/`vi2s`/`vuc2i`/… conversions |
| `SPECIAL3 funct 0x20` | 9 | BSHFL sub-op not handled (`wsbh`/`bitrev`) |
| `VFPU4 jump 0x14` | 6 | `vi2f` |
| `VFPU opcode 0x3c sub 0x4` | 3 | VFPU6 group, probably `vmscl` |
| `opcode 0x2f` | 1 | `cache`: treat as a no-op |
Exact sub-ops present in KZL (all instances in `.text`, from `tools/kzl/mipsdis.py`):
`bvf/bvt/bvfl/bvtl` 53 · `vi2f` 37 · `vfad` 37 · `bitrev` 22 · `vuc2i` 22 · `wsbw` 7 · `vus2i` 4 · `vs2i` 4 ·
`vmscl` 4 · `vf2in` 1 · `vsgn` 1 · `cache` 1. "VFPU7" is `vuc2i/vus2i/vs2i` (no `vf2h`), and the BSHFL gap is
`bitrev` + `wsbw` (`wsbh/seb/seh` were already handled).
- **Status (2026-10-19): closed.** Emitters for all of these are in [external/psp-recomp/tools/codegen_ext.py](external/psp-recomp/tools/codegen_ext.py), checked against Python models of
  PPSSPP's interpreter by a gcc-compiled test suite (`external/psp-recomp/tools/tests/test_codegen_ext.py`, 198 cases). Translating the switch cases (F-018) exposed
  two more: `vasin` (13 functions, now a bit-exact port of PPSSPP's `vfpu_asin` in `src/rt/vfpu_asin.c`, checked on all
  2,130,706,440 inputs in [-1, 1]) and `vnop`/`vflush` (18 functions, no-ops). The codegen now emits **42,300 of
  42,300 functions with 0 trapping stubs**, split into 230 TUs (`tools/kzl/gen.py`). All of them pass
  `gcc -fsyntax-only -Wall` without a warning, and an `-O2` build of all of them takes 2 min 49 s on 16 threads.
- **Impact:** the single 237 MB file **must be split** into about 200 translation units (TUs). MSVC, clang-cl and MinGW
  `ld` all struggle with one file that size; the sal063 README already warns about `ld` crashing.

### F-017 Jump tables are not recovered — Confirmed
sal063 sends every computed `jr` through `dispatch()`, which only knows function entry points. A `switch`
jump-table target inside a function is a hard error at runtime unless `SR_DISPATCH_PERMISSIVE` is set.
KZL has **243** non-return `jr` sites. The generated C has about 25k `dispatch(s…` call sites; most are `jalr`
virtual calls, which do work.
- **Impact:** add jump-table recovery (match the `lui/addiu base; sll; addu; lw; jr` pattern, bound the table with
  the preceding `sltiu`, then emit a C `switch` over local labels). Tail calls through `jr` must be told apart.
  The analysis side is done: see F-018.

### F-018 240 of the 243 computed jumps are switch tables — Confirmed
`tools/kzl/jumptab.py` recovers **240 tables with 4,480 cases** into [research/kzl_jumptables.toml](research/kzl_jumptables.toml).
Variants handled: `slti` and `sltiu` bounds; biased indices from sparse switches split into ranges
(`addiu rI, rS, -LO` with the bound on `rS`, on a separately biased temp, or in the guard's delay slot, plus one
positive bias); bound checks in a predecessor block; bounds on a copy of the index; table bases kept in an
s-register since the prologue.
- Cross-check: the tables sit back to back in `.rodata` with **no overlaps and no code pointers left in the gaps**
  (so no count is too high or too low), every table has a default target, and 880 entries point at the default
  (GCC's hole filling).
- The 3 other sites: `0x08CC5B48` is a computed tail call through a handler table (stays on `dispatch()`), and
  `0x08B219AC`/`0x08B219BC` are hand-written computed gotos in a native-call thunk (F-019). Their targets are in
  [config/kzl_overrides.toml](config/kzl_overrides.toml).
- **Impact:** the codegen can emit a `switch` for every computed jump. Unknown targets still fall to `dispatch()`,
  so a wrong table fails loudly instead of silently.

### F-019 Two codegen hazards in a hand-written thunk — Confirmed
The routine around 0x08B218A0 (probably the script → C++ call bridge) walks a type string and loads arguments into
`a1..t3` or `$f12..$f15` ('f' = 0x66) by jumping into two ladders of `b; move` pairs:
- **Get-PC idiom:** `jal 0x08B21928` at 0x08B21920 jumps to its own return address to load the PC into `ra`. A naive
  translation calls a phantom "function" that starts mid-routine. It is the only `jal/bal .+8` in the module.
- **Delay slot writes the jump register:** `jr t4; addiu t4, t4, 8`. sal063 emits the delay slot *before* reading the
  jump register for both `jr` and `jalr`, so it would jump to `t4 + 8`. The register must be captured first.
  GCC code never does this, but the generic emitter should be fixed in the fork anyway.
- **Impact:** both are handled by `codegen_ext.emit_jal_next()` / `emit_switch_jr()` and the overrides file. The fork's
  `jr`/`jalr` emission now reads the jump register before the delay slot everywhere.

---

## C. System-call (HLE) surface

### F-030 300 imported functions from 34 libraries — Confirmed
See [research/kzl_imports.toml](research/kzl_imports.toml) and [research/kzl_prx_survey.txt](research/kzl_prx_survey.txt).
All 300 NIDs have names in [research/nid_names.tsv](research/nid_names.tsv) (1,759 NIDs taken from PPSSPP's HLE tables
by `tools/kzl/nidnames.py`).

### F-031 sal063 already implements 159 of the 300 imports — Confirmed
See [research/hle_coverage_vs_sal063.txt](research/hle_coverage_vs_sal063.txt). The 141 missing imports split as follows:
- **About 69 networking imports, all safe to stub for an offline build:** sceNetInet 22, sceNetAdhoc 16,
  sceNetAdhocctl 7, sceNetApctl 6, sceNetResolver 5, sceHttp 5, sceNet 3, sceNetAdhocMatching 2, sceSsl 2,
  sceOpenPSID 1. They should report "WLAN switch off" (the game has an `ERROR_WLAN_SWITCH_OFF` path).
- **About 72 core imports that must be real:**
  - **GE:** `sceGeListSync`, `sceGeListEnQueueHead`, `sceGeListUpdateStallAddr`, `sceGeBreak`, `sceGeContinue`, `sceGeUnsetCallback`
  - **ThreadMan:** Fpl memory pools (`Create/Delete/TryAllocateFpl`), `sceKernelDelayThreadCB`, `sceKernelCheckCallback`,
    `ReferThreadStatus`, `GetThreadExitStatus`, `GetThreadmanIdList`, `SysClock2USec`
  - **IoFileMgr:** `sceIoDopen/Dread/Dclose`, `sceIoRemove`, `sceIoRmdir`, `sceIoChangeAsyncPriority`
  - **SasCore:** ADSR, reverb (`RevType/RevParam/RevEVOL/RevVON`), noise, pause
  - **sceAudio:** `Output2*` (the SRC channel) and the mic input functions (input can be stubbed)
  - **sceUtility:** MsgDialog, Netconf, GameSharing, USB/AV module loading, `GetSystemParamString`
  - **Other:** `sceMpegAvcDecodeMode`, `sceAtracGetBufferInfoForResetting`, three `sceUmd*` calls, sceCtrl 2, sceRtc 2, UtilsForUser 3
- **Impact:** most of the remaining HLE work is well-trodden ground; PPSSPP has reference behavior for all of it.

### F-032 mpeg.prx — Likely
It is encrypted, but it is Sony's standard libmpeg, which the game loads through ModuleMgr. sal063 already
implements 22 of the 23 sceMpeg imports and decodes the PMF video stream with Media Foundation (`src/rt/h264_mf.c`).
- **Impact:** do not try to load the module. Make `sceKernelLoadModule("…mpeg.prx")` succeed as a fake load,
  the way PPSSPP does.

### F-033 GE usage — Likely
The game imports 10 `sceGe_user` functions plus `SceGuSignal`, so it links libgu statically and builds its own
display lists, using stall-address streaming (`ListUpdateStallAddr`).
- **Impact:** the GE command processor needs correct stall and signal semantics. The renderer works per
  display list, not per draw call.

---

## D. Assets and content

### F-020 PSP.DAT archive — Confirmed (layout decoded, tree validates)
[tools/kzl/pspdat.py](tools/kzl/pspdat.py) lists and extracts it. Layout (little-endian u32):
- Header: `[0]` = TOC length after the first 0x18 bytes (TOC ends at 0x14F90), `[1]` = file records incl. duplicates
  (3,987), `[2]/[3]` = 0xFA3E01/0xFA3DB6 (unknown; not sizes in sectors), `[6]` = name pool size. The pool starts at 0x1C.
- After the pool: the root `{end, child_count}` with no name word, then 12-byte records `{name_off | 0x80000000 if dir, a, b}`.
  Files: `a` = offset, `b` = size. Dirs: `a` points at the first child, `b` = child count. Pointers are byte offsets from
  pool_end + 4, so record = (p - 4) / 12, and the root's `end` points one past the last record (5,005 records).
  Children are contiguous and the tree is depth-first. The first file starts at 0x15000.
- Contents: 1,018 dirs and 3,987 file records, but only **2,899 unique paths**: 165 files are stored 2–40 times at
  different offsets (all copies byte-identical, checked by SHA-1) to cut UMD seeks. 518 MB of records, 350 MB unique.
- File types (unique paths): `.luabin` 1,070, `.jsp` 655, `.core` 617, `.dat` 448, `.at3` 42, `.xm/.xmb/.xmh` 17 each,
  `.lua` 7, `.pmf` 6, `.png` 3. (The session-1 counts came from the name pool, which shares names between paths.)
- **Impact:** the runtime still reads PSP.DAT through `sceIo` and needs no unpacker. The lister maps I/O offsets in
  traces to file names, and it is the basis for later asset replacement.

### F-021 Chapter 5 is not on the disc — Confirmed
KZL.PRX references `CHAPTER5.BIN`, `HasChapter5`, `StartBrowserDownloadPatch`, `cache:lumps/Chapter5_Mission1.core`
and `chapter5/mission2/mission2.lua`. PSP.DAT has no chapter-5 lumps (it holds chapter1 through chapter4 only).
Chapter 5 was free DLC that was downloaded into the save directory.
- **Impact:** the runtime must map the game's `cache:` / `fatms0:` / `ms0:` devices to a user data folder, and the
  user supplies `CHAPTER5.BIN` themselves (we do not ship it). The `StartBrowserDownloadPatch` flow stays offline.

### F-022 Online features are permanently offline — Confirmed (the servers are gone)
Infrastructure mode (sceHttp/SSL/Inet with SVO/Medius) handled score uploads and the DLC download.
Ad-hoc mode handled co-op and versus.
- **Impact:** phase 1 ships offline only. Ad-hoc over LAN/UDP is a stretch goal (PPSSPP's adhoc layer is the model).

---

## E. Reference framework: sal063/PSP-recompilation-project

### F-040 What it gives us — Confirmed (cloned 2026-10-19, HEAD `da17b0e`; forked as the private mirror
`Tzeentchnet/psp-recomp`, our changes on branch `kzl`)
- **Python tools:** `analyze.py` (function discovery), `prxload.py` (applies type-A PRX relocations),
  `imports.py` (NID map), `codegen.py` (MIPS→C, VFPU included, with trace hooks), and the verification tools
  `tracediff.py`, `ppmdiff.py`, `funcdiff_cmp.py`, `microtest_gate.py`, `vfpu_fuzz_gen.py`.
- **C runtime** (`src/rt/`): `recomp.c` (dispatch), `sched.c` (threads), `hle.c` (110 KB of HLE), `iso.c`,
  `savedata.c`, `mpeg.c` + `h264_mf.c` (Media Foundation), `audio.c`, `pgf.c` (fonts), `osk_win.c`, and
  `ge.c` (133 KB GE command processor).
- **GPU:** `src/rt/gpu_sdl3vk/` is an SDL3 + Vulkan rasterizer (`ge_gpu.c` 74 KB, `psp_vert.inc` / `psp_frag.inc` shaders).
- **License: GPL-2.0-or-later** (it derives from PPSSPP). Anything we build on it inherits the GPL, and we must
  publish the complete corresponding source.
- **Impact:** the plan forks it. We reuse the tools and runtime, write **a new D3D12 backend behind `ge_shared.h`**,
  and keep the Vulkan backend as an A/B reference.

### F-041 Toolchain on this machine — Confirmed (updated 2026-10-19)
Installed: Python 3.12.10, CMake, Ninja, Git, gh, **VS 2022 Build Tools 17.14 (MSVC 14.44)**, **Windows SDK 10.0.26100**
(includes `dxc.exe`, `dxil.dll`, `fxc.exe`), and **WinLibs GCC 16.2 (UCRT)**. Only gcc is on the plain PATH;
MSVC needs a developer prompt (`vcvars64`).
**clang-cl 19.1.5** (with lld-link) was added to the Build Tools on 2026-10-19.
Still missing: **PIX**, and MSYS2 with SDL3/Vulkan for the unmodified sal063 reference build.
- **Impact:** the clang-cl CMake preset builds the game code (T-2.9). gcc runs the codegen unit tests.

### F-043 sal063 runtime details that matter at KZL scale — Confirmed (read from `src/rt/recomp.c`)
- The dispatch table is an open-addressing hash with a fixed **65,536 slots** ("homebrew has < a few thousand
  functions"). KZL's 42,641 functions load it to 65%, and every `jalr` (16k sites) goes through it.
- `sr_vwrite` saturates with float compares even when the lanes hold integer bit patterns. That matches PPSSPP for
  `vx2i` ("saturation does in fact apply"); for `vf2i` the D-prefix saturate must be masked off, which
  `codegen_ext` does.
- PSP fonts: sal063 ships PPSSPP's replacement `ltn0.pgf`/`jpn0.pgf`. They are not copied into this repo; the
  runtime should look for them in the user's PPSSPP install or ms0 folder.
- **Impact:** T-2.8 replaces the hash with a sorted table or perfect hash generated at build time.

### F-046 Odd code at 0x08804214 (near module_start) — Confirmed
`f_08804214` calls three functions, then `jal 0x00000000` (a call through an unrelocated null, likely a weak symbol
that was never linked), then `j 0x08804214` back to its own entry. sal063 emitted that `j` as a self tail call, which
recurses forever without tail-call optimisation; it is now a yielding `goto` loop.
- **Impact:** probably dead code, but if the runtime ever reaches it, the null call shows up as a dispatch miss at 0.

### F-045 The generated C needs GNU C — Confirmed
sal063's codegen emits `__builtin_clz` (clz/clo) and GNU statement expressions `({ ... })` (max/min), and the KZL
extensions add `__builtin_bswap32`. gcc and clang (including clang-cl) accept all of it; MSVC `cl` does not.
- **Impact:** D4's clang-cl is a requirement, not a preference. With it, all 231 TUs build at `-O2 -W3` with no
  warnings; CMake configure + build takes 49 s (16 threads), against 2 min 49 s for gcc `-O2`.

### F-042 Other recomp frameworks considered
- **N64Recomp / RT64** (Mr-Wiseguy): proven at scale, and its static-recomp pattern (lookup-table dispatch,
  per-function C, overlay handling) is a good design reference. It targets a different ISA, so we take ideas,
  not code.
- **XenonRecomp / XenosRecomp** (hedge-dev, the Unleashed Recompiled project): a mature recomp + D3D12/Vulkan
  shipping pipeline. Its D3D12 render-backend layout (plume) and its shipping practices (user supplies the game,
  hash check) are good models.
- **PPSSPP:** not a recompiler. It is the **ground truth** for HLE behavior, GE semantics (software renderer) and
  traces (`PPSSPPHeadless`). Its D3D11 backend (`GPU/D3D11`) is the closest existing map from PSP GE to Direct3D.
