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

### F-061 One backend descriptor now covers software, Vulkan, and future D3D12 GE paths — Confirmed
The existing GE boundary split responsibilities: `GeGpuHooks` carried primitive/flush callbacks in
`ge_shared.h`, while `gui.c` called the Vulkan renderer's init, direct-present, and shutdown functions by name.
That made a second GPU implementation require Vulkan-specific branches throughout the front end.

The seam is now one named `GeBackend` descriptor containing:
- lifecycle: `init`, direct framebuffer `present`, and `shutdown`;
- draw capture: triangle, sprite, line, and point;
- synchronization/coherency: `flush`, CPU-side `vram_dirty`, and GPU block `xfer`.

`ge.c` stores only the active descriptor through `ge_set_backend()` / `ge_backend_get()` and treats NULL as the
reference software rasterizer. The Vulkan implementation exports a static `"vk"` descriptor; it no longer
self-registers or clears global GE state. This is the same ABI the D3D12 implementation will export in T-4.2.

The interactive path now accepts `SR_GPU=sw|vk|d3d12`. `sw` keeps software GE rendering (with the existing GDI or
SDL presenter), `vk` requires the compiled SDL3/Vulkan implementation, and `d3d12` is recognized but reports that
it is unavailable until T-4.2 supplies its descriptor. Unknown values, unavailable builds, failed initialization,
and `SR_GPU=vk` combined with the legacy `SR_VIDEO=gdi` override fail before the scheduler starts. An unset
`SR_GPU` preserves the prior software default; `SR_GPU_GE` and `SR_VIDEO` remain legacy-compatible.

Validation:
- `kzl_driver` and `kzl_hle_tests` build; focused CTest passes 1/1.
- The HLE smoke test registers a fake descriptor, verifies getter identity and exact VRAM dirty forwarding, then
  clears it back to software mode.
- `ge_gpu.c` passes `gcc -std=c11 -fsyntax-only -Wall -Wextra` against current public Vulkan headers; only its
  pre-existing Vulkan partial-initializer warnings remain.
- `SR_GPU=vk`, `d3d12`, and an invalid value return exit 2 with the expected diagnostic in the non-GPU CMake build.
  `SR_GPU=sw` opens GDI and presents frame 1.
- A strict trace-free headless boot still reaches frame 1,200 without an unimplemented NID, and its language-screen
  PPM retains SHA-256 `B47E272E940B3EC9E999CFB79F999A8E973E029BA0D2D27F3D7DC1BF833D1C49`.
- **Impact:** T-4.1 is complete. T-4.2 can add a `"d3d12"` descriptor and selector branch without changing GE
  command processing, software fallback, or call sites.

### F-062 The D3D12 foundation is runnable before native GE shaders land — Confirmed
`src/rt/gpu_d3d12/device.cpp` now supplies the `"d3d12"` descriptor introduced by F-061. Its initialization path:
- creates an SDL3 window and retrieves the native `HWND` from
  `SDL_PROP_WINDOW_WIN32_HWND_POINTER`;
- enumerates adapters in high-performance preference order, rejects software adapters by default, and supports
  the Microsoft Basic Render Driver only through explicit `SR_D3D12_WARP=1`;
- creates a feature-level-11_0-or-newer D3D12 device, direct and copy command queues, timeline fences/events,
  three command allocators, and one resettable graphics command list;
- creates a three-buffer 480x272 BGRA8 `DXGI_SWAP_EFFECT_FLIP_DISCARD` swapchain on the SDL HWND;
- partitions 4,095 shader-visible CBV/SRV/UAV descriptors and a persistently mapped 24 MiB upload buffer evenly
  across the three fenced frame slots, and exposes reusable 256-entry RTV and 64-entry DSV descriptor pools.

The native GE shader pipeline starts in T-4.3. For now the descriptor intentionally leaves primitive hooks NULL,
so `ge.c` runs its reference rasterizer. At each display flip, the D3D12 backend converts guest 5650/5551/4444/
8888 pixels into its current upload-ring slice, copies them into the current swapchain buffer, presents, signals
that slot's fence, and only reuses it after completion. This exercises the actual device, swapchain, allocator,
upload, and synchronization paths instead of leaving T-4.2 as unreachable scaffolding. SDL keyboard/gamepad
state is returned through the existing GUI input contract.

Build integration is dual-path: the fork Makefile compiles the C++ device object alongside SDL3/Vulkan, while
root CMake keeps the dependency-free software build as its default and enables D3D12 with
`KZL_ENABLE_D3D12=ON` plus an SDL3 package. Unavailable builds and `SR_GPU=d3d12` combined with
`SR_VIDEO=gdi` still fail with exit 2. D3D device/present failures use the fatal backend return instead of
silently falling back to GDI.

Validation:
- Default and D3D12 clang-cl driver/test targets build; focused CTest passes 1/1 in both configurations.
- The same source compiles warning-free as C++17 with MinGW g++, matching the fork Makefile toolchain.
- Hardware selection chose an NVIDIA GeForce RTX 5070 at feature level 12_1. The explicit WARP path chose
  Microsoft Basic Render Driver and also presented successfully.
- A 10-frame unpaced boot wrapped the three in-flight frame partitions without a fence, allocator, copy, or
  presentation failure. A 1,200-frame D3D12-presented boot reached SELECT YOUR LANGUAGE and produced the exact
  reference PPM SHA-256 `B47E272E940B3EC9E999CFB79F999A8E973E029BA0D2D27F3D7DC1BF833D1C49`.
- The optional D3D12 debug layer is not installed on this host
  (`DXGI_ERROR_SDK_COMPONENT_MISSING`, `0x887a002d`); `SR_D3D12_DEBUG=1` reports that error and aborts
  initialization rather than pretending validation ran.
- **Impact:** T-4.2 is complete with a live synchronization/resource-allocation base. T-4.3 can compile embedded
  DXIL and T-4.4 can allocate root-signature descriptors directly from the exposed per-frame rings.

### F-063 The Vulkan GE shader contract maps directly to a 64-byte Shader Model 6 interface — Confirmed
The Vulkan backend's GPU stages operate after CPU transform/lighting and vertex decoding, so their portable
contract is much smaller than the full PSP GE:
- a 32-byte vertex (`float4` screen position/rw, `float2` u*rw/v*rw, `float` fog, UNORM8 RGBA);
- four noperspective varyings (UV, reciprocal W, fog, color);
- one sampled 2D texture and sampler;
- four 16-byte state vectors for texture/alpha/depth flags, texture environment, fog color, and texture size/
  render-target offset.

`gpu_d3d12/shaders/psp_vs.hlsl` and `psp_ps.hlsl` now implement that contract in native HLSL. The vertex shader
maps the 512x272 PSP target into D3D clip space; unlike Vulkan's positive-height viewport, D3D maps NDC +Y to the
top, so the HLSL expression is `1 - y/136` rather than `y/136 - 1`. It passes UV/rw/fog/color as noperspective
values. The pixel shader preserves the GLSL uber-shader's 0..255 arithmetic for texture functions 0..7,
RGBA/color-double flags, transform-mode min/max depth discard, programmable alpha test, fog, clear-mode bypass,
and doubled-source-alpha premultiplication. Fixed-function blend/depth/write-mask state remains a later PSO task.

DXC reflection verifies the ABI rather than relying on source spelling:
- VS inputs are `POSITION0 float4`, `TEXCOORD0 float2`, `TEXCOORD1 float`, and `COLOR0 float4`; its output and the
  PS input match as `SV_Position`, `TEXCOORD0..2`, and `COLOR0`, with all user varyings noperspective.
- `PSPConstants` is exactly 64 bytes at `b0`: `cfg` offset 0, `texenv` 16, `fogcol` 32, `texsize` 48.
- The texture is `t0`, sampler is `s0`, and the pixel output is `SV_Target0`.

`tools/compile_d3d12_shaders.py` compiles `vs_6_0`/`ps_6_0` with HLSL 2021, strict mode, warnings as errors, O3,
and stripped debug/reflection chunks, then writes deterministic C initializers with source and DXIL SHA-256
stamps. It auto-discovers the newest x64 Windows SDK DXC or accepts `--dxc`/`DXC`. `--check` recompiles into a
temporary directory and rejects stale checked-in output. The current blobs are:
- vertex: 2,484 bytes, SHA-256 `58A851B54F25AF153D483EB79C3C781AB024F86E89BEBBA90B9F7AE1788BD4D2`;
- pixel: 4,240 bytes, SHA-256 `30CAF54B125FAF184F96528005ABC29F4F2A55AB2FB9E4E71410E45218C6BA9B`.

Validation used Windows SDK DXC 1.8.2502.11. Direct generation/check, `mingw32-make check-shaders-d3d12`, and the
CMake `kzl_d3d12_shaders`/`kzl_d3d12_shaders_check` targets all pass. D3D12 and dependency-free builds succeed,
their focused CTests pass 1/1, the embedded arrays compile warning-free under MinGW C++17, and a D3D12 smoke boot
still presents through the software framebuffer path. The bytecode is deliberately not bound yet: T-4.4 defines
the root signature and T-4.6 creates PSOs.
- **Impact:** T-4.3 is complete with a reflected, reproducible shader ABI. T-4.4 can define one `b0` root-constant
  block, one `t0` descriptor table, and `s0` sampler without changing either shader.

### F-064 The complete GE shader binding contract costs only 18 root DWORDs — Confirmed
The reflected T-4.3 interface now has a live D3D12 1.0 root signature:

| Root slot | Visibility | Binding | Purpose |
|---|---|---|---|
| 0 | pixel | 16 x 32-bit constants at `b0` | `cfg`, `texenv`, `fogcol`, `texsize` |
| 1 | pixel | two contiguous SRVs at `t0..t1` | decoded texture and reserved CLUT |
| 2 | pixel | one sampler descriptor at `s0` | per-draw filter/wrap state |

The constants cost 16 DWORDs and each descriptor table costs one, for 18 of D3D12's 64-DWORD root-signature
budget. Hull, domain, and geometry access are denied; input-assembler access remains enabled for the decoded
vertex stream. Two clamp samplers are also embedded in the signature: point-filtered `s1` and linear-min/mag
with point mip selection at `s2`. The shader currently reads dynamic `s0`; the static registers let later common
paths avoid descriptor allocation without changing the root signature.

Dynamic samplers use a new 768-entry shader-visible heap divided into 256 descriptors for each of the three
fenced frame slots. `ged3d12_sampler_alloc()` has the same reset-after-fence lifetime as
`ged3d12_srv_alloc()` and `ged3d12_upload_alloc()`. Every command-list reset now:
1. resets that frame's SRV and sampler cursors;
2. binds both shader-visible heaps and the GE root signature;
3. allocates and binds a safe null RGBA texture at `t0`, null `R32_UINT` CLUT buffer at `t1`, and dynamic
   clamp-point sampler at `s0`;
4. writes zero to all 16 root constants.

Those defaults make the binding state valid before the first native GE draw and actively exercise the
descriptor rings/root tables now, rather than leaving them dormant until T-4.5. Later code replaces the null
descriptors and constants per batch. Root-parameter and sampler-register enums are exported by `device.h` so
callers cannot depend on unexplained numeric slots.

Validation: both clang-cl targets build and focused CTest passes 1/1; the same device source compiles
warning-free with MinGW C++17. The signature serializes, creates, binds, and cycles descriptor partitions on an
NVIDIA GeForce RTX 5070 (10-frame run) and Microsoft WARP (frame-1 run), with the existing software framebuffer
presentation unchanged.
- **Impact:** T-4.4 is complete. T-4.5 can upload decoded vertices and bind real state/texture descriptors without
  another root-signature revision.

### F-065 The existing GE seam is the complete D3D12 CPU vertex decoder — Confirmed
`ge.c` already resolves the PSP-specific work before invoking a backend:
- u8, u16, and float texture coordinates, normals, positions, and weights;
- 5650, 5551, 4444, and 8888 colors;
- zero through eight skinning weights, transform/lighting, viewport projection, clipping, and fog;
- through-mode coordinates;
- non-indexed, u8, u16, and u32 index streams;
- points, lines/strips, triangles/strips/fans, and rectangle pair assembly.

The four backend primitive hooks therefore receive the same finished `GeVtx` values used by the reference
rasterizer. Duplicating raw PSP layouts in D3D12 would create a second decoder and a correctness risk. T-4.5
instead packs that seam into the reflected HLSL ABI:

| Offset | Field | D3D12 input |
|---:|---|---|
| 0 | `x, y, z, rw` | `POSITION0`, `float4` |
| 16 | `u, v` | `TEXCOORD0`, `float2` |
| 24 | fog | `TEXCOORD1`, `float` |
| 28 | clamped packed RGBA | `COLOR0`, `R8G8B8A8_UNORM` |

The 32-byte size and every semantic offset are compile-time assertions. Screen x/y use the Vulkan path's exact
`floor(value * 16 + 0.375) / 16` snap. Flat triangles and lines copy the PSP's last provoking-vertex color.
Rectangles recover perspective UVs from `u*rw`/`v*rw`, apply the half-texel adjustment, and emit six vertices;
lines and points likewise become six-vertex triangle-list quads. A compact batch record retains each primitive's
range, kind, and perspective flag for the PSO stage.

GE hooks run before presentation, while the D3D12 upload allocator becomes valid only after the swapchain frame
fence is acquired. The backend therefore grows CPU-side pending arrays during GE execution, then copies the
finished stream into the active frame's persistent upload partition during `present`. The frame limit is 240,000
vertices (7.68 MB, about 7.32 MiB), leaving about 692 KiB in the 8 MiB partition for the 544 KiB BGRA
presentation upload.
Capacity, allocation, and partial-capture failures are fatal and explicit. Until native batch submission becomes
the presentation source, all hooks return zero and the reference rasterizer still generates the displayed
framebuffer.

Focused tests lock down packing and every expansion rule. A `ge_execute_op` matrix independently proves that
u8/u16/float positions and UVs, all four packed colors, and non-indexed/u8/u16/u32 indices reach the decoded
backend callback correctly. Default/D3D12 clang-cl builds, both CTest configurations, warning-clean MinGW builds,
hardware/WARP boots, and a 1,200-vblank capture stress run all pass without upload exhaustion.
- **Impact:** T-4.5 is complete. T-4.6 can create PSOs against one triangle-list vertex ABI and use retained batch
  boundaries without revisiting PSP vertex formats or changing upload lifetime.

### F-066 A 16-byte canonical key captures all current D3D12 PSO-static GE state — Confirmed
The entire live graphics PSO varies on only these fields:

| Bytes | State |
|---:|---|
| 0-3 | blend enable, source factor, destination factor, color operation |
| 4-7 | source-alpha factor, destination-alpha factor, alpha operation, color-write mask |
| 8-11 | depth enable, depth write, comparison function, cull mode |
| 12-15 | RTV and DSV formats |

The builder maps PSP blend and depth enums to D3D12 once, before hashing. It carries forward the Vulkan backend's
current approximations: source-side doubled-alpha factors are paired with shader premultiplication later;
destination doubled-alpha factors use ordinary destination alpha; two unequal fixed blend colors preserve the
source constant and round the destination to zero/one; absolute difference uses subtract. Clear mode disables
blend/culling and independently derives RGB, alpha, and depth writes from `clear_mode`. `draw_prim` has already
reordered culled triangles, so D3D12 uses clockwise fronts and back-face culling just like Vulkan.

Everything not baked into a PSO is intentionally absent. Texture identity/format, CLUT state, alpha test,
fog, texture function, min/max depth kills, and perspective flags belong to shader constants/descriptors.
Scissor and blend color will be dynamic command state. Attachment addresses and strides select render-target
objects, not shader pipelines. Excluding those fields prevents equivalent PSOs from multiplying across draws.

Every captured primitive batch stores this key while the matching `GeState` is still live. The cache computes
64-bit FNV-1a, probes 512 power-of-two slots, and compares all 16 bytes before accepting a hit, so hash collisions
cannot select the wrong state. A miss synchronously creates an `ID3D12PipelineState` using the live root signature,
embedded DXIL, four-element input layout, triangle-list topology, BGRA8 target, optional D16 depth, and mapped
fixed-function state. The PSO is immediately bound; native draw submission remains deferred so the software
framebuffer stays authoritative during bring-up. T-4.15 can layer asynchronous compilation and a disk
`ID3D12PipelineLibrary` over the same stable key.

Focused tests prove that PSO-relevant changes alter the key/hash while shader-only texture fields do not, and lock
clear/sprite/fixed-color behavior. RTX hardware and WARP compile the same five hashes during the boot sequence.
A 1,200-frame hardware stress run creates exactly those five entries and then only hits them, with no creation
failure or cache exhaustion. A separate graceful-close run records 2,214 lookups, 2,209 hits, five misses, and
zero failures, and waits for the graphics queue before releasing the cached COM objects.
- **Impact:** T-4.6 is complete. The next native submission stage can bind vertex slices and per-draw dynamic
  state without recompiling equivalent fixed-function combinations.

### F-067 Presentation must decouple the fixed PSP display texture from the resizable swapchain — Confirmed
The software GE always produces a 480×272 framebuffer, while an SDL3 window can have any logical size, DPI scale,
or aspect ratio. Copying that upload directly into a swapchain buffer therefore only works while the swapchain is
also fixed at 480×272. T-4.7 introduces a persistent default-heap BGRA8 texture at the PSP display dimensions.
Each frame first copies the existing row-pitched upload into that texture, transitions it to an SRV, and then
draws a fullscreen triangle through a dedicated one-table root signature and static linear-clamp sampler.
The whole back buffer is cleared opaque black before the draw, so any uncovered area is deterministic letterbox
or pillarbox space rather than stale swapchain contents.

Aspect fitting uses the actual SDL pixel size, not its logical window size. An integer cross-product decides
whether width or height constrains the image; that dimension is assigned exactly and only the other is computed
in floating point. The viewport is centered at the true 480:272 ratio, and the scissor floors its origin and
ceils its far edge so fractional pixels cannot clip the triangle. This intentionally preserves 480:272 rather
than rounding it to nominal 16:9.

On a pixel-size change, the backend waits for the direct queue, releases all three old back buffers, resizes the
flip-discard chain, reacquires each buffer, and recreates its RTV. Zero-sized/minimized observations defer resize
work and retain the valid chain. Focused tests cover zero dimensions, exact 960×544, square letterboxing,
portrait letterboxing, and 1920×1080 pillarboxing, including fractional scissor bounds. Hardware and WARP boots
both execute the new root signature, PSO, copy, and draw. A live hardware test recreates the chain at 1478×844
and 878×1410 (the DPI-scaled wide and portrait client sizes) and shuts down cleanly; a 1,200-frame hardware run
reports no resize, resource-state, presentation, or D3D12 device error.
- **Impact:** T-4.7 is complete. The swapchain is now presentation-only and can retain this stable aspect-correct
  path when T-4.8/T-4.9 replace the software framebuffer source with native cached render targets.

### F-068 PSP texture identity requires metadata, palette state, and immutable content versions — Confirmed
PSP texture addresses are mutable views into RAM/VRAM, not durable resource identities. The same address can be
redrawn after its bytes or palette change, while two draws with identical encoded content should reuse one D3D12
resource. The cache therefore separates a canonical metadata key from encoded-content hashes. Its 96-byte
texture key includes eight addresses, PSP-aligned buffer widths, dimensions, format, swizzle mode, the legal mip
count, CLUT format/sharing state, and a full hash of the selected palette. Filter, wrap, mip filtering, and signed
sixteenth-level LOD bias form a separate 8-byte sampler key so sampling changes do not duplicate texture memory.

The shared GE decoder remains the source of truth rather than a D3D12-specific implementation. It now decodes
5650, 5551, 4444, 8888, CLUT4/8/16/32, and PSP-layout DXT1/3/5 at any of eight levels. PSP DXT blocks reverse the
usual PC member order. Separate mip palettes advance by 16 entries for CLUT4 and alternate 256-entry banks for
16-bit CLUT8; CLUT16/32 do not add a level offset. Buffer widths obey the PSP's format-specific masks, with a
masked zero selecting the minimum 16-byte row. Mip tails are accepted only while registered dimensions halve
correctly, and are capped to the number D3D12 can represent down to 1×1.

Each cache miss creates an immutable content version. Captured batches hold serial-protected handles, so a later
write can create a new version without changing an earlier draw's texture. Small inputs are fully hashed on every
lookup. Large inputs use a distributed quick hash during primitive capture, then receive one full verification
per texture per presented frame; explicit invalidation always forces full verification. This catches unsignaled
between-frame RAM changes without rescanning a 512×512 texture for every primitive.

The fixed 512-slot cache owns decoded RGBA8 staging and default-heap mip resources. Pending decoded data is
bounded to 64 MiB, upload footprints are row-pitch aligned, and unique texture/sampler descriptors are reused
within each fenced frame. When full, the backend waits for the graphics queue and retires the 128 least-recently
used versions. CPU, DMA, and `TRXKICK` dirty spans invalidate every overlapping mip range. `TEXFLUSH` deliberately
does not invalidate content: observed command streams issue it frequently without changing bytes, and treating
it as a write created duplicate identical versions.

Focused tests cover every format, swizzling, DXT interpolation and alpha, shared/separate palettes, mip
registers, PSP row alignment, byte ranges, sampler mapping, key sensitivity, and block-transfer notification.
Hardware and WARP produce identical keys and full hashes in ten-frame boots. A graceful hardware run records
4,608 lookups, 4,572 hits, 36 misses/uploads, 18 invalidations, zero evictions, and no D3D12 failures. A separate
1,200-frame hardware run completes without cache exhaustion or device errors.
- **Impact:** T-4.8 is complete. Native draw submission can bind stable texture resources while T-4.9 adds
  GPU-resident framebuffer aliases and render-to-texture transitions over the same dirty-range model.

### F-069 Framebuffer identity and CPU visibility require versioned targets plus explicit ownership — Confirmed
A PSP framebuffer is a typed view over aliased eDRAM, not an object identified by address alone. D3D12 therefore
uses a canonical 16-byte key containing normalized physical color/depth addresses, color/depth strides, and color
format. Zero color stride means 512, zero depth stride inherits color stride, and all fixed 512×272 color/depth
ranges must remain inside the 2 MiB PSP eDRAM aperture. Color data is stored as BGRA8 on the GPU; tested reversible
conversion preserves the PSP's 5650, 5551, 4444, and `0xAABBGGRR` 8888 layouts.

The cache owns sixteen color and sixteen depth resources with serial-protected handles, capture generations,
explicit D3D12 states, and fenced LRU reuse. A format or stride reinterpretation first materializes any
GPU-newer overlapping target, then creates the requested view from authoritative guest bytes. Views already
referenced by the current capture generation cannot be evicted, so batches before and after a reinterpretation
retain the resource they captured. Clean targets retain a full CPU-content hash, catching unnotified eDRAM
changes before presentation or reuse without imposing watched callbacks on every software-rasterizer pixel.

An unswizzled, single-level texture with matching format and stride can reference a cached target directly when
its rectangle remains inside the 512×272 resource. Sampling the target currently bound for rendering first copies
it to a reusable feedback snapshot; non-feedback aliases use the target SRV. Cached display buffers bypass the
software upload and copy their visible 480×272 rectangle directly into the existing presentation texture.
Uncached and movie buffers retain the original conversion/upload fallback.

CPU visibility is an ownership transition. `gpu_newer` color targets enable fast-gated VRAM read and pre-write
hooks in the generated memory accessors. A CPU load synchronously reads back overlapping GPU-owned data. A CPU
store reads it back before writing, then the normal dirty callback invalidates overlapping framebuffer and
texture views. DMA, MPEG output/clears, and CPU `TRXKICK` fallback perform the same pre-write preservation around
their bulk host-memory operations. Vulkan now participates in this shared contract as well. GPU-owned depth
readback is deliberately deferred to T-4.10, where depth range and stencil behavior become authoritative.

Compatible `TRXKICK` operations decode the PSP's masked strides, encoded dimensions, pixel size, and source/
destination coordinates into an exact D3D12 texture copy. Both cached views must be distinct, in bounds, and
identical in format, stride, and bytes per pixel; the source must be GPU-authoritative. Successful copies also
update the guest-VRAM mirror and invalidate overlapping aliases. All incompatible cases fall back to the existing
CPU implementation rather than approximating a copy.

Default and D3D12 clang-cl builds and CTests, focused Make/shader checks, and strict MinGW compilation pass.
Hardware and WARP boots create the same two observed color/depth pairs. Safe mode performs two GPU readbacks for
each cached presentation (762 readbacks over 381 hits) without failure. The exact final binary reaches PSP vcount
1,200 with 490,296 texture lookups, 490,236 hits, 60 uploads, 18 texture invalidations, 122,580 framebuffer
uploads, 61,291 cached presentations, two live color targets, two live depth targets, and no stale handles,
descriptor exhaustion, resource-state errors, or D3D12 failure. The no-ISO workload naturally performs no
render-to-texture alias or GPU block-transfer operations, so those paths currently rely on focused metadata and
resource-binding coverage. Native draw calls remain disabled; cached targets mirror the authoritative software
renderer until the remaining shader state is complete.
- **Impact:** T-4.9 is complete. T-4.10 can make color/depth targets GPU-authoritative through native draws while
  retaining a tested identity, aliasing, presentation, copy, and CPU-coherency foundation.

### F-070 PSP fragment state fits a 28-DWORD draw block, but complete stencil and dither need destination access — Confirmed
The authoritative software GE now preserves the PSP fragment order: texture function and color doubling, alpha
test, fog, masked RGB color test, stencil test, depth test/write, blending, dithering, and component write masks.
Framebuffer alpha is stencil storage rather than ordinary source alpha. Normal draws therefore retain destination
alpha, while clear mode can replace it. Stencil compares the masked reference against masked destination alpha,
then applies independent test-fail, depth-fail, or depth-pass operations. The implementation covers keep, zero,
replace, invert, saturating increment/decrement, alpha write masks, and the PSP's effective stencil precision:
none in 5650, one bit in 5551, four bits in 4444, and eight bits in 8888.

Depth testing now has separate verdict and write phases, so a depth failure can mutate stencil without
incorrectly storing depth. D16 remains the native depth format and preserves all 65,536 PSP values; transform-mode
fragments outside `minz`/`maxz` are discarded by the shader rather than clamped. Dithering uses the signed-nibble
4×4 GE matrix after software blending for every framebuffer format, including clear-mode draws.

Each captured D3D12 batch now owns a canonical 112-byte `b0` snapshot:
- four configuration DWORDs for texture mode/flags, alpha test, and the 16-bit depth range;
- texture-environment color, fog color, texture dimensions, and render-target alias offsets;
- masked color-test state and complete stencil test/operation/write-mask/format state;
- four packed signed dither rows.

The root signature consequently grows from 16 to 28 constants, for a total cost of 30 root DWORDs including the
two descriptor tables, still below D3D12's 64-DWORD limit. HLSL evaluates color test after fog and applies the
ordered dither matrix. PSOs preserve destination alpha by default. The shader can directly represent the safe
always-pass stencil depth-pass subset (zero or masked replace when every stored stencil bit is writable), because
those results do not require reading the destination. Other stencil comparisons and fail/depth-fail/invert/
increment/decrement operations require destination alpha; exact dithering also belongs after blending. Those
operations will use the destination-aware shader/copy design already required by T-4.11 rather than a knowingly
incorrect fixed-function approximation.

Focused tests exercise pure comparison/operation rules and real sprite rasterization through the GE command
path, including alpha preservation, all three stencil outcomes, partial masks, color-test ordering, depth
preservation, and clear dithering. Default/D3D12 builds, CTests, Make/DXC verification, and strict MinGW pass.
Hardware and WARP accept the expanded root signature and embedded DXIL; both produce the exact saved frame-10
SHA-256 (`90AB1AE6...D3E7C3`). A graceful 120-vblank run reuses four PSOs across 39,214 lookups with no creation
failure, records 39,200 texture lookups and 4,904 cached presentations, and drains normally; safe mode completes
9,842 readbacks without error.
- **Impact:** T-4.10 is complete at the current staged-native boundary. The batch ABI now carries every fragment
  input, the software path is the exact oracle, and T-4.11 has an explicit requirement for destination-aware
  stencil, blending, logic operations, and post-blend dithering before native draws become authoritative.

### F-071 Ordered per-batch snapshots provide exact PSP destination fragments without ROVs — Confirmed
PSP blending cannot be represented exactly by ordinary D3D12 blend state. Its add/subtract equations use signed
integer terms `((2 * color + 1) * (2 * abs(factor) + 1)) >> 10`; doubled inverse-alpha factors can be negative;
min, max, and absolute-difference ignore configured factors; and source and destination fixed colors are
independent. Logic operations occur after blending and dithering. Stencil is framebuffer alpha, with test-fail,
depth-fail, and depth-pass mutations, while component masks apply to native 5650/5551/4444/8888 storage bits.
The shared software GE now implements those rules as the authoritative oracle, including all 16 logic operations
and raw-reference stencil replacement after masked comparison.

Each captured batch is one ordered primitive, so D3D12 can obtain the exact previous destination without raster
order views: copy that batch's cached BGRA8 color target and D16 depth target to reusable SRV snapshots before
issuing its draw. The color/depth pair is bound at `t2`/`t3`; the shader evaluates stencil and depth, exact blend
math, signed post-blend dithering, logic operations, native packing, and per-bit masks, then returns final color
and either new or preserved `SV_Depth`. Cached depth resources are `R16_TYPELESS`, exposed as `D16_UNORM` DSVs
and copied to an `R16_UNORM` SRV snapshot. The PSO disables fixed-function blending and uses depth `ALWAYS` with
writes enabled, making the shader the single fragment-state authority.

The canonical batch state is 160 bytes/40 DWORDs: the prior 28-DWORD texture/test/dither contract plus blend mode,
both fixed colors, framebuffer write mask, logic operation, clear mode, depth state, and a clamped D3D12 scissor.
The root signature adds a second two-entry SRV table, for 43 root DWORDs total. Safe null destination descriptors
are bound at frame start. `SR_D3D12_DESTINATION_SAFE=1` invokes the new per-draw snapshot/bind API for every staged
batch, allowing actual transition/copy/SRV validation while native draws remain disabled and the software GE
remains authoritative; enabling replay now would render every primitive twice.

Focused tests cover exact blend vectors, signed doubled-alpha factors, min/max/absolute-difference, all logic
operations, logic-after-dither rasterization, raw stencil-reference writes, state capture, normalized PSOs, and
inclusive/clamped scissors. Default and D3D12 builds/CTests, Make/DXC verification, and strict MinGW pass.
Hardware and WARP accept the expanded signature, typeless depth/SRV resources, snapshots, and rewritten shader.
An RTX destination-safe frame-10 capture remains byte-identical to the saved reference
(`90AB1AE6E95A03BA789B8D07B0AD407A6BA7644C2E9079B7F8F8F8DEB9D3E7C3`).
- **Impact:** T-4.11 completes the fragment-accuracy contract at the staged-native boundary. Future native
  submission must call the destination snapshot API immediately before each ordered draw and suppress the
  matching software rasterization in the same ownership transition.

### F-072 PSP patches require quantized scalar evaluation after morph-before-skin decoding — Confirmed
A PSP logical vertex with morphing is not one ordinary record selected at draw time. Its vertex type declares up
to eight aligned target records stored consecutively, so its effective stride is one decoded target size times the
morph count. Position, UV, color, normal, and every bone weight are blended independently with
`MORPHWEIGHT0..7`. Skinning then consumes that single morphed model vertex: each enabled 4×3 bone matrix transforms
the morphed position, each 3×3 portion transforms its normal, and the weighted result enters the ordinary
world/view/projection and lighting pipeline. A test with target-dependent positions, weights, and bone scale proves
the order rather than only testing a commutative translation case.

Bezier and B-spline surfaces likewise cannot use ordinary Bernstein/Cox-de Boor floating-point weights when exact
GE behavior matters. Each tessellation step is first rounded toward the patch center to `k/256`. The GE evaluates
control columns before rows with fixed-grid de Casteljau/de Boor lerps; colors use `(channel << 7) | 0x7f` and
integer lerps before shifting back to eight bits. Normals come from the last two intermediate points along each
axis using GE-style products and row sums. At one-third and two-thirds these rules produce observable position,
UV, and color differences from textbook polynomial evaluation.

The command path now implements those rules for indexed or sequential controls, open spline edges, generated or
interpolated UVs, patch-facing normals, and the PSP's triangle, three-edge zigzag-line, and duplicated-point cell
orders. Bezier patches are submitted U-major; splines share one global segment grid. Commands with fewer than four
controls on either axis draw nothing but still advance the declared controls, matching ordinary GE pointer
consumption. Excessive subdivisions reduce the larger factor until no more than 65,536 output vertices are needed.

Focused tests cover exact thirds, explicit float UV/fixed RGBA interpolation, morph and morph-before-skin results,
two-bone normal rotation through environment-map UVs, all patch primitive topologies, reversed 8-bit indices,
invalid dimensions, logical/index pointer advancement, and the tessellation cap. Default and D3D12 builds/CTests,
Make/DXC verification, strict MinGW, RTX/WARP boots, and saved pre-change GE/frame hashes pass.
- **Impact:** T-4.12 closes the remaining CPU geometry features needed by the shared software oracle and the staged
  D3D12 backend. Future shader-side vertex decoding can compare against one authoritative logical-vertex and patch
  contract instead of inventing separate morph, skin, or curve behavior.

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
