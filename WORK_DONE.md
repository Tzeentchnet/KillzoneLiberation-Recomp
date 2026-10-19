# WORK DONE — archive

A dated log of finished work, newest first. Each entry lists what was done, what it produced, and the
findings or tasks it touched. Items move here from [TODO.md](TODO.md) when they are ticked off.

---

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
