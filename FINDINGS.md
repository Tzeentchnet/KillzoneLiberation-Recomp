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

### F-047 PPSSPP boots KZL; the real boot-path HLE surface is 79 functions — Confirmed
Reference runs on 2026-10-19 with PPSSPP 1.20.4: the desktop build (60 s, `-d` log) and a locally built
PPSSPPHeadless (`-i --graphics=software --timeout=40`). Both boot to the front end and render (3,385 / 4,885 frame flips).
- Confirms F-004 and F-010: `sceKernelStartModule(0x11b, 0xb, 0x09F0CE20 = "modulename", ...)`, and the export table
  lands at 0x08D8F3BC, i.e. load base 0x08804000. The bootloader first tries `ms0:/PSP/GAME/UCUS98646/KZL.PRX`, and there
  are about 9 s between loading and starting KZL.
- The game opens exactly one file, `disc0:/PSP_GAME/USRDIR/PSP.DAT` (async I/O, sector 0x4819), so all assets go through
  the archive (F-020).
- At start-up it probes free memory with ~24 MB allocations that back off in halving steps (`BlockAllocator` errors in
  the log are expected).
- 79 HLE functions are called; **22 have no sal063 handler** ([research/ppsspp_boot_hle_60s.txt](research/ppsspp_boot_hle_60s.txt),
  from `tools/kzl/hlesummary.py`): `sceKernelDelayThreadCB`, `sceGeListUpdateStallAddr`, `sceCtrlReadBufferPositive`,
  `sceGeContinue`, `sceGeListSync`, `sceGeUnsetCallback`, Fpl (`Create/Delete/TryAllocate`), Vpl (`Create/Delete/TryAllocate`),
  `sceKernelCheckCallback`, `sceKernelTerminateThread`, `sceUmdReplaceProhibit`, `sceImposeGetLanguageMode`,
  `sceIoChangeAsyncPriority`, `sceKernelDcacheWritebackInvalidateAll`, `sceAudioOutput2Reserve/ChangeLength/OutputBlocking`,
  `sceCtrlSetSamplingCycle`. A few may be bootloader-only calls, which our runtime never makes.
- PPSSPP itself leaves only `sceKernelPowerTick` (harmless) and the bootloader's `sceKernelStopUnloadSelfModuleWithStatus`
  unimplemented on this path.
- **Impact:** these 22 are the P0 HLE work for the headless milestone (T-3.4, T-3.5, T-3.6, T-3.9, T-5.2). Stock
  headless has no per-instruction trace; T-2.11 needs a small patch to the interpreter loop
  (`RunUntilWithChecks` in `Core/MIPS/MIPSTables.cpp`).

### F-048 PPSSPP traces: what the recompiled side must match — Confirmed
[tools/ppsspp/psprecomp-trace.patch](tools/ppsspp/psprecomp-trace.patch) (PPSSPP v1.20.4) makes PPSSPPHeadless write the
psp-recomp trace format from its interpreter loop; [tools/kzl/ppsspp_trace.py](tools/kzl/ppsspp_trace.py) records a
trace (5M steps from `module_start` in 3 s, 229 MB). Things the first steps show:
- **Thread start state** (PPSSPP `PSPThreadContext::reset`): r1–r31, hi, lo = `0xDEADBEEF`; f0–f31 and v0–v127 =
  `0x7f800001`; VFPU prefixes S/T = `0xe4`, D = 0; VFPU CC = `0x3f`; REV = `0x7772ceab`; RCX0–7 = `0x3f800001`,
  `0x3f800002`, `0x3f800004`, `0x3f800008`, then `0x3f800000` ×4; fcr31 = `0x00000e00`; fpcond = 0. The guest stores
  these values (for example `sw s1` writes `0xdeadbeef` at step 2), so the runtime must start threads the same way.
- **module_start entry:** `ra = 0x08000030` (kernel trampoline), `a0 = 11`, `a1 = 0x09FFFEF0` (argp copied onto the top
  of the start thread's stack), `sp = 0x09FFFEB0` before the prologue.
- **HLE results:** PPSSPP fills r1, r4–r15, r24, r25, hi and lo with `0xDEADBEEF` after most HLE calls. sal063's
  `sr_syscall` does the same on purpose, so the patch leaves PPSSPP's filling on. (PPSSPP skips it for a few functions
  via `hleSkipDeadbeef`; the runtime should copy those as traces expose them.)
- **Kernel trampolines** at `0x08000000+` show up as steps with many register writes (thread switches, callbacks);
  5 in the first 5M steps.
- **Coverage:** the first 5M steps reach only 344 distinct PCs. From step 12,789 the game sits in an O(n²) sort of
  8-byte pairs at 0x08A06C50–0x08A06CD0 (498,253 iterations of the inner loop). A useful trace gate needs several
  start points or longer windows, not just the first 5M instructions.
- **Impact:** T-3.1 must set the thread state above, and T-2.11 must decide how to treat trampoline steps.
- Found while writing the trace's memory addressing: sal063 computed the `lv.q`/`sv.q` address from the raw immediate,
  but bits 0–1 are not offset bits (bit 0 is the register's high bit, bit 1 a flag). **53 accesses in KZL** (4 + 49) were
  1–3 bytes off. Fixed in the fork (offset = `imm & 0xFFFC`, as in PPSSPP).

### F-049 Recompiled module_start matches PPSSPP step for step; memory manager is the next gap — Confirmed
`kzl.exe --image` (fork `src/rt/driver.c`, runtime built without SDL3/Vulkan) seeded from the PPSSPP trace header
(`# init`, `# kernel next_uid`, `# mem`) runs `module_start` for **71 steps identical to PPSSPP**, registers and memory
writes included. Fixes needed to get there:
- **Import stubs were never emitted.** KZL names its stub sections per library (`.sceStub.text.<lib>`), but
  sal063 only looked for `.sceStub.text`, so no stub was generated and the first call aborted in `dispatch()`.
  Both the analyzer and the codegen now match the prefix (300 stubs, 42,600 functions).
- **Kernel UIDs** must continue from the oracle's next handle (0x11d here; PPSSPP has used 0x110–0x11c for the
  bootloader). The trace header carries it and the runtime adopts it.
- `tracediff.py` treats a syscall word on either side as matching, because each loader patches import-stub delay
  slots with its own encoding.

With `--sched` the game's threads run until the first missing HLE call, `sceKernelCreateFpl` (thread 0x11e), as
F-047 predicted. But sal063's user-partition allocator is a bump pointer that never frees, ignores low/high
placement, and **never fails or checks the partition end**. KZL probes free memory at start-up by asking for about
24 MB and halving until an allocation succeeds (F-047), so with this allocator the first request "succeeds" and
runs past 0x0A000000 into the thread stacks. PPSSPP also takes thread stacks from the top of the same partition.
- **Impact:** port PPSSPP's `BlockAllocator` (first fit, 256-byte grain, low/high/fixed placement, free, failure) and
  build partition memory, thread stacks, Fpl and Vpl on it before adding more HLE calls (T-3.13). → done, F-050

### F-050 With PPSSPP's allocator ported, KZL's memory probe matches PPSSPP exactly — Confirmed
The fork's `src/rt/kmem.c` is a literal C port of `BlockAllocator`. `tools/tests/test_kmem_blockalloc.py` compiles PPSSPP's
own `BlockAllocator.cpp` next to it and runs 320,000 random operations through both, comparing every result and the full
block list: 0 mismatches. Four injected bugs were each caught. Partition memory, FPLs and thread stacks are built on it.
- **User memory at the probe**, from PPSSPP's debug log (each failed allocation prints the block list) and from our run
  (`SR_MEMLOG=1`): `usersystemlib` 0x08800000–0x08804000, the module 0x08804000–0x08EA8800 (image 0x6A4710 bytes rounded
  to 256), `user_main`'s 64 KB stack at 0x08EA8800 (attr 0x80404000 asks for a low stack), then one free block of
  0x1147800 bytes. `module_start`'s 0x400 stack at the partition top is freed when it returns, and the probe needs that:
  without it the largest block would be 0x400 smaller.
- **The probe is done with FPLs**, not partition memory: `sceKernelCreateFpl("DummyHeap", 2, 0, size, 1)` and
  `DeleteFpl`, with sizes that move up and down until the largest one that fits is found (0x1147800 fits, 0x1147801 does
  not). Then it creates `GameHeap` of 0xFBF800. Our run makes the same 25 DummyHeap requests (the same 6 succeed, all
  at 0x08EB8800), the same 6 deletes, and the same `GameHeap` at 0x08EB8800.
- **The start thread's UID and stack come from the seed.** PPSSPP's `FillStack` writes the thread UID at k0+0xC0 and the
  stack base at k0+0xC8, and the trace's `# mem` lines cover k0. So the runtime takes UID 0x11C and reserves
  0x09FFFC00–0x0A000000 without changing the trace format. `user_main` then gets UID 0x11D, as in PPSSPP.
- **UIDs fall one behind PPSSPP after `user_main`.** During KZL's first `sceKernelDelayThread(10000)`, BOOT.BIN calls
  `sceKernelStopUnloadSelfModuleWithStatus`, and PPSSPP creates a "bootloader" thread for it (UID 0x11E), then unloads
  BOOT.BIN. We never run BOOT.BIN, so our first DummyHeap gets 0x11E where PPSSPP's gets 0x11F, and every later handle
  is one lower. This doesn't change addresses or the order of calls, but a scheduler-mode trace diff will flag each
  returned handle (T-3.14).
- **Vpl is not needed.** KZL imports no Vpl function, and neither `MaxFreeMemSize` nor `TotalFreeMemSize`. The Vpl
  calls in the PPSSPP log come from BOOT.BIN (`temp_vpl`). Of the FPL calls, KZL imports only Create, Delete and
  TryAllocate; the rest are implemented for completeness.
- The runtime's guest-callback stacks (vblank at 0x09DF0000, GE/mpeg callbacks at 0x09DF8000) sat inside what is now
  GameHeap (0x08EB8800–0x09E78000). They now come from the kernel partition (0x083E0000 and 0x083F0000).
- **Next stops:** strict mode now stops at `sceRtcGetCurrentTick` (a known sal063 gap, T-3.9). With `SR_PERMISSIVE=1`,
  `user_main` gets as far as `sceDisplaySetFrameBuf`, then waits on an event flag that nothing sets: GE/callback
  work (T-3.4, T-3.6).
- **Impact:** T-3.13 is done. The FPL part of T-3.4 is done. T-3.14 covers the bootloader UID.

### F-051 KZL's renderer needs PPSSPP's display-list manager: libgu waits on GE signal interrupts — Confirmed
After `sceDisplaySetMode`, `user_main` waits on the event flag `SceGuSignal` (created with pattern 1, attr 0x200),
and the only thing that sets it is a GE interrupt. sal063's GE ran each list to completion inside
`sceGeListEnQueue`, ignored stall addresses and dropped `SIGNAL`, so the flag was never set and every thread blocked.
What PPSSPP 1.20.4 does on this path (debug log, lines ~16618–16950):
- `sceGeSetCallback` registers signal handler 0x08a6d8a4 and finish handler 0x08a6d920 as GE sub-interrupts
  `cbid*2` and `cbid*2+1`. The lists end in `SIGNAL` with behaviour 2 (HANDLER_CONTINUE, token 1 or 2) + `END`, then
  `FINISH` + `END`. At the signal the list stops, the GE interrupt runs the signal handler (a0 = token,
  a1 = signal_arg, a2 = END pc + 4 because the SDK is above 2.00.10), and it calls `sceKernelSetEventFlag(SceGuSignal, 1)`.
  The list then resumes, and the finish handler runs at `FINISH`.
- The signal handler calls `sceGeContinue()` itself on token 1 (it returns ALREADY, 0x80000020, because the list is
  running), and the vblank handler 0x08a61a04 calls `sceGeContinue()` every frame (0, no current list).
- KZL uses stall addresses heavily (~1,150 `sceGeListUpdateStallAddr` in 60 s) and `sceGeListSync`/`DrawSync`.

The fork's `src/rt/gelist.c` ports PPSSPP's `GPUCommon` list manager (EnqueueList, ProcessDLQueue, Execute_End with
every signal behaviour, Break, Continue, ListSync, DrawSync, InterruptEnd) and `GeIntrHandler`. `ge.c` now executes
single commands (`ge_execute_op`), so the list manager owns the pc, the 32-entry call stack and the per-list offset.
`src/rt/intr.c` ports PPSSPP's sub-interrupt table, which vblank now uses too. That fixed a latent bug: PPSSPP calls
a vblank sub-handler with a0 = sub-interrupt number and a1 = argument, and sal063 passed the argument in a0.
With `SR_GELOG=1` our run prints the same sequence as PPSSPP's log: signal, handler, `SetEventFlag`, resume,
finish handler, `ALREADY=sceGeContinue()`.
- **Differences left:** a list completes as soon as its commands have run, and a GE interrupt runs when the sceGe call
  that raised it returns (or when the interrupt handler that raised it returns). PPSSPP adds an estimated GE
  duration, so a `ListSync`/`DrawSync` there can block briefly and let another thread run. The list context in
  `PspGeListArgs` is saved on the host, not in guest memory. List IDs start at 0, while PPSSPP's first KZL list is
  0x29 because BOOT.BIN used 41 before it (the same issue as the UIDs, T-3.14).
- **Impact:** T-3.6 is done. A scheduler-mode trace diff (T-2.11) will see thread interleaving differ wherever a GE
  wait would have blocked in PPSSPP.

### F-052 Callbacks, the memory stick, and two sal063 HLE bugs on the boot path — Confirmed
With the GE fixed, the game reached its first PSP.DAT reads and then made a virtual call through a NULL object
(`jalr` at 0x08837744, called from 0x08837678). Comparing our HLE sequence with PPSSPP's
(`tools/kzl/hleseq.py`) found three causes:
- **Kernel callbacks were not modelled.** `sceKernelCreateCallback` only returned a UID. KZL registers
  "MSCallback" through `sceIoDevctl("fatms0:", 0x02415821)` and "VolatileMemoryPowerCallback" through
  `scePowerRegisterCallback`. PPSSPP notifies both at once and runs them at the game's next
  `sceKernelCheckCallback`. Our `sceIoDevctl` was a plain `return 0` that never wrote its output either, so the game
  saw no memory stick and skipped its savedata step. The fork's `src/rt/callback.c` ports PPSSPP's callbacks: they
  run on the owning thread at `sceKernelCheckCallback` and in every ...CB wait, on the thread's stack with PPSSPP's
  128-byte register save area, and a callback returning non-zero is deleted. `sceIoDevctl` now ports PPSSPP's UMD,
  memory stick and fatms0 commands (stick inserted, FAT assigned, 1.5 GB free).
- **`sceIoLseekAsync` decoded the wrong arguments.** It reused the `sceIoLseek32` handler, which reads a 32-bit
  offset from a1. The real call takes a 64-bit offset in a2:a3 and whence in t0, as `sceIoLseek` does. Every seek went
  to 0, so the game's three 64 KB reads of the PSP.DAT TOC all returned the first block. Its archive lookup then failed,
  which produced the NULL object.
- **`sceKernelSetCompilerVersion` was registered on the SDK-version handler**, so KZL's second call replaced the SDK
  version 0x02070010 with the compiler version 0x00030306 (PPSSPP logs both in decimal: 34013200 and 197382). The GE
  code now depends on the SDK version. Below 2.00.10 a SUSPEND signal pauses the list, the signal handler gets
  a2 = 0, and `Break`/`Continue` return -1 instead of the newer error codes.
- **Impact:** the boot now follows PPSSPP's call order through both savedata dialogs (LIST, then AUTOLOAD of
  DATA00/KZL.BIN), `sceUtilityLoadAvModule` ×3, the SAS audio thread and the UMD checks. Our savedata dialog finishes
  in fewer polls than PPSSPP's, which runs it on a "ScePafJob" thread for ~300 ms.

### F-053 Headless milestone: the recompiled game reaches the main menu with no unimplemented import — Confirmed
In strict mode (unimplemented NIDs stop the run), `kzl.exe --sched` with `PSP_ISO` set boots to **SELECT YOUR
LANGUAGE** (about vblank 1,000) and, with a scripted CROSS at vblank 1,500 and START/CROSS presses after it
(`SR_PADSCRIPT`), to the **PLAY A GAME** main menu (Campaign / Challenge Games / Multiplayer), drawn by the runtime's
software GE. It ran for 120 s, ~6,800 vblanks, with no unimplemented NID. Without input it stays on the language screen for at least 90 s
(~475,000 HLE calls, ~3,350 frame flips, polling the pad with `sceCtrlPeekBufferPositive`).
- New HLE on the path, all following PPSSPP: `sceRtcGetCurrentTick` (microseconds since 0001-01-01) and
  `sceRtcGetTime_t`, `sceIoChangeAsyncPriority`, `sceImpose{Get,Set}LanguageMode`, `sceAudioOutput2*` (SRC channel),
  `sceCtrlPeekBufferPositive`, `sceCtrlSetSamplingCycle`, `sceUmd{Activate,Deactivate,ReplaceProhibit}` with the UMD
  callback, `sceKernelDcacheWritebackInvalidate{Range,All}`, `sceKernelGetGPI`, `sceMpegAvcDecodeMode`.
- After the language is chosen the game fake-loads `BINPSP/mpeg.prx` and plays the intro through sceMpeg (F-032).
- `SR_DLDUMP=<vblank>` writes every executed GE command of that frame (address, word, list start/resume/end) to
  `gedump_f<vblank>.txt`. A language-screen frame is 9,328 commands in 2 lists, each stopped once by its signal.
- **Impact:** T-3.10 is done. Next: the HLE that the main menu and campaign need (T-3.4/T-3.5 leftovers, Netconf and
  GameSharing dialogs for the multiplayer entries), then the D3D12 backend (phase 4), which can now be fed from real menu frames.

### F-054 Remaining ThreadMan and functional directory I/O HLE match PPSSPP — Confirmed
The four remaining T-3.4 imports now have modeled state instead of success stubs:
`sceKernelReferThreadStatus` writes PPSSPP's modern 108-byte thread-info ABI, `sceKernelGetThreadExitStatus` distinguishes
unknown/running/dormant threads, `sceKernelGetThreadmanIdList` enumerates typed thread/semaphore/event-flag/FPL/callback
UIDs (including filtered thread states and truncated output), and `sceKernelSysClock2USec` splits a 64-bit clock into
seconds and microseconds. Thread creation, natural/explicit exit, forced termination and deletion maintain the metadata
and typed UID registry.

The functional T-3.5 directory/removal calls are also implemented. `sceIoDopen/Dread/Dclose` enumerate both host-backed
storage and ISO9660 directories with PSP `SceIoDirEnt`/`SceIoStat` layouts; `sceIoRemove`, `sceIoRmdir` and host
`sceIoGetstat` report real file/directory metadata and errors. Writable paths now preserve their directory hierarchy,
with `fatms0:` and `cache:` sharing the `ms0:` tree and a read fallback for files created by the old flattened mapping.
Standard descriptors 0–2 are reserved, fixing the first host file being opened as fd 1 and its writes being discarded
as stdout.

Validation:
- `kzl_hle_smoke` passes under CTest with the KZL ISO, covering ThreadMan ABI/error/list behavior, clock conversion,
  host file/stat/list/remove/rmdir behavior, closed/invalid directory handles, and real ISO directory enumeration.
- The PPSSPP allocator differential remains at 320,000 operations over 80 seeds with 0 mismatches.
- A clean clang-cl build of `kzl_driver` succeeds. A strict headless run then reached vblank 3,600 with no unimplemented
  NID; captured frames show SELECT YOUR LANGUAGE, MAIN MENU, and PLAY A GAME, confirming the F-053 milestone.
- **Impact:** T-3.4 is complete. T-3.5 remains open only for PPSSPP's asynchronous `SceIoAsync` worker/delay behavior;
  the requested synchronous directory and removal surface is complete.

### F-055 Async file I/O now runs through a scheduled SceIoAsync helper — Confirmed
KZL's imported async file operations no longer execute to completion in the calling thread. Each participating
descriptor owns PPSSPP-style pending/result/close state and a reusable scheduler-visible `SceIoAsync` helper with a
0x200-byte stack. The helper inherits the caller's priority or the default/per-fd value configured by
`sceIoChangeAsyncPriority`, consumes a thread UID, performs reads and seeks, delays completion, and wakes
`sceIoWaitAsync`/`sceIoWaitAsyncCB` waiters. `sceIoPollAsync` now returns 1 while pending without consuming anything.

Completed results remain busy until consumed, overlapping operations return `SCE_KERNEL_ERROR_ASYNC_BUSY`, a second
wait returns `SCE_KERNEL_ERROR_NOASYNC`, and all results are written as signed 64-bit values. `sceIoCloseAsync` keeps
the fd and worker alive until its result is consumed, while a failed `sceIoOpenAsync` still returns a temporary fd whose
result contains the open error before that fd is released. Open/read/seek/close use PPSSPP's low-end timing estimates
rather than an inline success fallback.

Validation:
- The scheduler-driven `kzl_hle_smoke` case observes the helper in the thread list, verifies its waiting state,
  pending polls, overlap errors, read/seek results and data, consumed-result errors, deferred close, and failed-open
  cleanup. The full smoke test, including real ISO enumeration, passes under CTest.
- The allocator differential still passes 320,000 operations over 80 seeds with 0 mismatches, and `kzl_driver` builds
  with clang-cl.
- In a strict paced boot, exactly one persistent `SceIoAsync` thread was created at configured priority 0x24. The run
  reached vblank 3,600 with no unimplemented NID and again rendered PLAY A GAME.
- **Impact:** T-3.5 is complete. The helper now consumes the missing async-thread UID; exact whole-boot UID alignment
  remains the separate bootloader/GE-list work in T-3.14.

### F-056 Offline networking covers every KZL import and reaches the WLAN-off UI — Confirmed
The fork's `src/rt/net.c` registers all 69 imports grouped as networking in F-031, both imported `sceWlan` calls,
and the existing non-imported `sceWlanDevIsPowerOn` handler. Lifecycle and handler-registration calls stay local and
succeed; the runtime never opens a host socket, resolves DNS, or makes an HTTP request. `sceWlanGetSwitchState` reports
off, infrastructure calls return `SCE_NET_APCTL_ERROR_WLAN_SWITCH_OFF`, ad-hoc control returns
`SCE_NET_ADHOCCTL_ERROR_WLAN_SWITCH_OFF`/`DISCONNECTED`, ad-hoc sockets return `NOT_CONNECTED`, and Inet operations
return -1 with PSP errno `ENETDOWN` (115). Numeric IPv4 parsing remains functional.

The console identity remains deterministic: `sceWlanGetEtherAddr` writes the stable six-byte MAC already used by the
runtime, and `sceOpenPSIDGetOpenPSID` writes a stable 16-byte ID derived from it. A mechanical import audit finds all
71 KZL Net/Http/Ssl/OpenPSID/Wlan NIDs registered, and `kzl_hle_smoke` invokes every one while checking the key return
codes and output buffers.

Validation: the focused CTest passes with the KZL ISO and the clang-cl driver links. In a strict paced run, scripted
input selects PLAY A GAME → MULTIPLAYER → COMBAT ZONE - ADHOC → JOIN GAME. The game calls `sceNetInit`,
`sceNetAdhocInit`, `sceNetAdhocctlInit`, `AddHandler`, and `Connect`, then cleanly tears down the stack and renders
**"NETWORK ERROR OCCURRED, WLAN SWITCH HAS BEEN TURNED OFF"** with no unimplemented NID.
- **Impact:** T-3.7 is complete. Online infrastructure remains intentionally disabled (F-022); no host networking
  surface is exposed.

### F-057 Writable VFS defaults to the per-user LocalAppData tree — Confirmed
IoFileMgr now maps `ms0:` to `%LOCALAPPDATA%\KZLRecomp\ms0` by default. `fatms0:` and the game's `cache:` device
resolve to the same tree, so a user-supplied `CHAPTER5.BIN` is visible through every alias without placing content in
the repository. Paths retain their PSP directory hierarchy and reject `..`; `SR_FSDIR` remains an explicit
test/developer override. If neither an override nor `LOCALAPPDATA` is available, the runtime reports the configuration
error instead of silently writing to a relative `fs` directory. `disc0:` remains backed by the ISO9660 reader.

Validation: `kzl_hle_smoke` writes `cache:CHAPTER5.BIN`, stats it through `fatms0:`, reads the same bytes through
`ms0:`, and verifies the physical file under the default LocalAppData root. The focused CTest passed with the KZL ISO,
both runtime targets built, and a strict turbo scheduled boot with `SR_FSDIR` unset reached frame 1,200 without an
unimplemented NID.
- **Impact:** T-3.3 is complete. Chapter 5 remains user-supplied content (F-021), but all relevant PSP device names now
  expose the required persistent location.

### F-058 The MPEG intro reaches PPSSPP's exact video EOF — Confirmed
The real `/interface/movies/gameintro_psp.pmf` is 11,573,248 bytes: a 2,048-byte PSMF header followed by
11,571,200 bytes (5,650 packs) of program stream. Its header timestamps are 90,000..7,402,305, a duration of
7,312,305 ticks or 81.248 s. At 3,003 ticks per 29.97 fps frame, that is exactly **2,435 AVC frames**.

Two runtime shortcuts had made the intro's duration incorrect:
- The six-byte PSMF timestamps were read from bytes 0..4 and omitted byte 5. PPSSPP's layout is
  `b5 | b4<<8 | b3<<16 | b2<<24 | b1<<32 | b0<<36`; the old values were 351..28,915 instead of
  90,000..7,402,305.
- `sceMpegGetAvcAu` removed exactly one 2 KiB ring packet per frame. PPSSPP instead updates ring availability during
  `sceMpegAvcDecode` according to demux progress, so packet count and frame count are independent. The headless model
  now consumes toward `packets * elapsed_timestamp / duration_timestamp` during decode.

The ring reaches zero after pack 5,643, whose MPEG-2 SCR is 7,309,366: less than one frame before the 7,312,305-tick
video duration. PPSSPP still emits three reordered decoder frames after that drain. The runtime now parses pack SCR,
marks that decoder tail as buffered, and continues AU/decode calls until the declared timestamp instead of treating an
empty ring as immediate video EOF.

A patched PPSSPP v1.20.4 oracle, driven by the same Cross-at-vblank-1,500 script through the new
`PSPRECOMP_PADSCRIPT` hook, recorded for the first intro session:

| Call | PPSSPP | Runtime |
|---|---:|---:|
| `sceMpegRingbufferPut` | 5,644 | 5,643 |
| successful `sceMpegGetAvcAu` | 2,435 | 2,435 |
| `sceMpegAvcDecode` | 2,435 | 2,435 |
| final no-data `sceMpegGetAvcAu` | 1 | 1 |

The one feed-call difference is internal buffering: both expose the same AU/decode sequence and then
`FlushAllStream` -> `FreeAvcEsBuf` -> stream unregister -> `Delete` -> `RingbufferDestruct` -> `Finish`.
The PPSSPP patch applies cleanly to tag v1.20.4, both clang-cl runtime targets build, the focused CTest passes with the
real ISO, and a strict turbo run completes the movie and resumes presentation without an unimplemented NID.
- **Impact:** T-3.2 is complete. The blank-frame headless decoder now has PPSSPP-equivalent timing and EOF behavior;
  real H.264 output remains the SDL3/Media Foundation path.

### F-059 Standalone boot reproduces the PPSSPP module-start contract without a trace — Confirmed
The normal runtime no longer needs a PPSSPP trace header to initialize KZL. `kzl.exe --boot` maps the pre-relocated
`kzl_image.bin` at 0x08804000, writes BOOT.BIN's 11-byte `"modulename\0"` argument into reserved usersystemlib
memory, and lets the scheduler copy it onto a newly allocated start-thread stack. The pre-relocated image satisfies
the loader's relocation requirement; `module_start` itself owns the weak constructor/cplinit checks on its startup
path, so no out-of-band initializer call is required.

The standalone path reserves the UIDs consumed before KZL was started, then reuses the existing
PPSSPP-compatible `start_reset()` state builder. Its launch diagnostic matches the oracle exactly:

| Field | Standalone value |
|---|---:|
| start-thread UID | 0x11C |
| stack | 0x09FFFC00..0x0A000000 (0x400 bytes) |
| k0 | 0x09FFFF00 |
| sp/fp | 0x09FFFEB0 |
| a0 | 11 |
| a1 | 0x09FFFEF0 |
| ra | 0x08000030 |

This also preserves PPSSPP's poisoned GPR/FPR/VFPU defaults, stack fill, k0 control block, and argument-copy layout.
The first game-created `user_main` thread receives UID 0x11D, as in the oracle.

Validation: `kzl_driver` and `kzl_hle_tests` build, focused CTest passes 1/1 with the retail ISO, and a strict
trace-free run reaches the SELECT YOUR LANGUAGE screen at frame 1,200 with no unimplemented NID. The legacy
trace-seeded `--image` path remains identical to PPSSPP for all 71 available recompiled steps; its comparison ends
only when that intentionally short runtime trace returns from `module_start`.
- **Impact:** T-3.1 is complete. PPSSPP traces remain an optional differential oracle rather than a runtime boot
  dependency; T-3.14 separately tracks the later BOOT.BIN unload-thread UID consumed after startup.

### F-060 Executed call targets introduce no missing function boundaries — Confirmed
The PPSSPP v1.20.4 instrumentation now has a compact `PSPRECOMP_CALLTRACE` mode. From the interpreter's checked
loop it records each unique `(source PC, jal/jalr, runtime target)` edge after `module_start` is reached. `jalr`
destinations are read from the source register before the instruction executes, so virtual calls and callbacks are
resolved without reconstructing register state from a multi-gigabyte instruction trace. Function replacements are
disabled while either trace mode is active.

`tools/kzl/ppsspp_calls.py` runs a bounded capture; `tools/kzl/calltargets.py` validates the format, relocates and
analyzes KZL.PRX, classifies targets outside KZL (the seven observed targets are in the loaded MPEG module), and
fails if any KZL executable target is absent. Its report is [research/kzl_calltargets.txt](research/kzl_calltargets.txt).

The 90-second deterministic boot capture found:

| Metric | Count |
|---|---:|
| unique call edges | 12,399 |
| unique targets | 4,560 |
| targets inside KZL executable sections | 4,553 |
| effective codegen function inventory | 42,600 |
| missing in-module targets | **0** |

The analyzer has 42,601 raw seeds. The one seed omitted from codegen, 0x08B21928, was executed and correctly matched
the existing `[[jal_next]]` override: the `jal .+8` at 0x08B21920 is a get-PC idiom inside one function, not a new
function. This explains the inventory difference and ensures the audit does not turn a known false boundary back
into generated code. The older 42,641 figure in the original task predates the stale-`lui` cleanup and later import
stub accounting.

The call-target parser/classifier unit tests pass, the patched PPSSPPHeadless builds, and the regenerated patch passes
plain `git apply --check` against a clean detached v1.20.4 worktree.
- **Impact:** T-2.7 is complete with no new override entries. Future gameplay captures can use the same strict tool;
  any newly exercised indirect target missing from the inventory will fail the audit instead of reaching a runtime
  dispatch miss.

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
The root CMake build explicitly selects `llvm-lib.exe` beside clang-cl; otherwise CMake can pick WinLibs `ar.exe`
from PATH and pass it incompatible MSVC librarian flags.
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
