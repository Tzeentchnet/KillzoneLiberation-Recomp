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

### F-004 The bootloader is thin and can be skipped — Likely
BOOT.BIN strings: `disc0:/PSP_GAME/USRDIR/`, `KZL.PRX`, `sceKernelLoadModule`, `sceKernelLoadModuleDNAS`,
`ms0:/PSP/GAME/UCUS98646/KZL.PRX` (a development path), an inflate/Adler-32 routine, `-upload_dir`, `-upload_file`.
KZL.PRX contains the strings `-patch_failed` and `DidPatchFailToLoad`.
- **Impact:** the runtime should load `KZL.PRX` itself and not recompile the bootloader. **TODO T-1.6:** work out
  exactly which argv/argp the bootloader passes to KZL's `module_start` (for example `-patch_failed`), and copy that
  behavior.

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
- **Impact:** about one to two weeks of codegen work closes this gap. The single 237 MB file **must be split** into
  about 200 translation units (TUs). MSVC, clang-cl and MinGW `ld` all struggle with one file that size; the sal063
  README already warns about `ld` crashing.

### F-017 Jump tables are not recovered — Confirmed
sal063 sends every computed `jr` through `dispatch()`, which only knows function entry points. A `switch`
jump-table target inside a function is a hard error at runtime unless `SR_DISPATCH_PERMISSIVE` is set.
KZL has **243** non-return `jr` sites. The generated C has about 25k `dispatch(s…` call sites; most are `jalr`
virtual calls, which do work.
- **Impact:** add jump-table recovery (match the `lui/addiu base; sll; addu; lw; jr` pattern, bound the table with
  the preceding `sltiu`, then emit a C `switch` over local labels). Tail calls through `jr` must be told apart.

---

## C. System-call (HLE) surface

### F-030 300 imported functions from 34 libraries — Confirmed
See [research/kzl_imports.toml](research/kzl_imports.toml) and [research/kzl_prx_survey.txt](research/kzl_prx_survey.txt).

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

### F-020 PSP.DAT archive — Partially reverse-engineered (Hypothesis on the TOC layout)
- Header words: `[0]=0x14F78` (TOC size?), `[1]=0xF93` (3,987 entries), `[2]=0xFA3E01`, `[3]=0xFA3DB6` (two sector
  counts or checksums?), `[6]=0x64D0` (size of the name pool). The name pool starts at offset 0x1C and holds 1,292
  unique NUL-terminated names that entries share.
- After the name pool come 12-byte records that look like `{u32 a, u32 b, u32 flags|name_off}`.
  Bit 31 set means a directory, with `b` as its child count.
- File types: `.luabin` 582, `.core` 216 (Guerrilla's level and resource "lumps"), `.at3` 58, `.jsp` 56,
  `.xm/.xmb/.xmh` 30 each (probably sound banks), `.lua` 12, `.pmf` 6 (movies), `.png` 3.
- **Impact:** the runtime does not need an unpacker, because the game reads PSP.DAT through `sceIo` from `disc0:`.
  A tool that lists the archive is still worth building for debugging (mapping I/O traces to file names), and later
  for asset replacement.

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

### F-040 What it gives us — Confirmed (cloned 2026-10-19, HEAD `da17b0e`)
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

### F-041 Toolchain gap on this machine — Confirmed
Installed: Python 3.12.10, CMake, Git, gh. Missing from PATH: `cl`, `clang`, MSYS2/MinGW.
D3D12 needs the Windows SDK, DXC and ideally PIX.
- **Impact:** phase 0 installs VS 2022 Build Tools (MSVC + clang-cl), the Windows SDK and PIX. MSYS2 UCRT64 is
  needed only to build the unmodified sal063 Vulkan reference.

### F-042 Other recomp frameworks considered
- **N64Recomp / RT64** (Mr-Wiseguy): proven at scale, and its static-recomp pattern (lookup-table dispatch,
  per-function C, overlay handling) is a good design reference. It targets a different ISA, so we take ideas,
  not code.
- **XenonRecomp / XenosRecomp** (hedge-dev, the Unleashed Recompiled project): a mature recomp + D3D12/Vulkan
  shipping pipeline. Its D3D12 render-backend layout (plume) and its shipping practices (user supplies the game,
  hash check) are good models.
- **PPSSPP:** not a recompiler. It is the **ground truth** for HLE behavior, GE semantics (software renderer) and
  traces (`PPSSPPHeadless`). Its D3D11 backend (`GPU/D3D11`) is the closest existing map from PSP GE to Direct3D.
