# WORK DONE — archive

A dated log of finished work, newest first. Each entry lists what was done, what it produced, and the
findings or tasks it touched. Items move here from [TODO.md](TODO.md) when they are ticked off.

---

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
