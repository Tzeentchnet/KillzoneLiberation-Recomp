# PPSSPP oracle with psp-recomp traces

`psprecomp-trace.patch` makes PPSSPPHeadless write the per-instruction trace format of the
psp-recomp toolkit (`external/psp-recomp/tools/TRACE_FORMAT.md`), so a run of PPSSPP's
interpreter can be diffed against our recompiled code with `tools/tracediff.py`. It can also
write a compact, deduplicated stream of executed `jal`/`jalr` edges for function-boundary audits.
It applies to PPSSPP **v1.20.4** and touches four files:

- `Core/MIPS/MIPSTables.cpp`: the instruction and call-edge writers in the interpreter's checked loop.
- `Core/HLE/sceKernel.h`: a read-only accessor for the next kernel object handle.
- `Core/HLE/sceCtrl.cpp`: optional backend-specific, frame-based scripted controller input for
  reproducible UI paths.
- `headless/Headless.cpp`: turns off function replacements while tracing (they skip guest
  instructions), captures golden frames from the software renderer, and supports an isolated
  memstick root. The 0xDEADBEEF filling after HLE calls stays on, because the psp-recomp runtime
  reproduces it.

## Build (Windows, VS 2022 Build Tools)

```
git clone --depth 1 --branch v1.20.4 --recurse-submodules --shallow-submodules https://github.com/hrydgard/ppsspp.git
cd ppsspp
git apply <this repo>/tools/ppsspp/psprecomp-trace.patch
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
msbuild Windows\PPSSPP.sln -t:PPSSPPHeadless -p:Configuration=Release -p:Platform=x64 -m
```

The exe lands in `Windows\x64\Release\PPSSPPHeadless.exe`. `tools/kzl/ppsspp_trace.py` looks for
it in a `ppsspp` checkout next to this repo, or wherever `PPSSPP_HEADLESS` points.

## Environment variables read by the patched build

| Variable | Meaning |
|---|---|
| `PSPRECOMP_TRACE` | output file; tracing is off when unset |
| `PSPRECOMP_TRACE_START` | hex PC: start at its first execution (default: from the first instruction) |
| `PSPRECOMP_TRACE_STEPS` | stop after this many steps (default 5,000,000) |
| `PSPRECOMP_TRACE_TARGET` | name written in the header (default `ppsspp`) |
| `PSPRECOMP_CALLTRACE` | compact unique `jal`/`jalr` edge output file |
| `PSPRECOMP_CALLTRACE_START` | hex PC that arms the call trace (normally `08804000`) |
| `PSPRECOMP_PADSCRIPT` | optional v2 input script described below |
| `PSPRECOMP_CAPTURE_MANIFEST` | strict 50-frame golden manifest |
| `PSPRECOMP_CAPTURE_DIR` | output directory for the 50 PPMs and `capture.complete` |
| `PSPRECOMP_MEMSTICK` | isolated PPSSPP memstick root (must contain `PSP/SAVEDATA`) |

Run with the interpreter (`-i`). The JIT never reaches the traced loop. When the trace is complete
the build writes `<trace>.done`, which `ppsspp_trace.py` uses to stop the emulator.

## Trace header

Before step 0 the trace carries the state the recompiled run must start from. The fork's
`src/rt/driver.c` (`kzl.exe --image ...`) reads all of it:

```
# psp-recomp trace v1 oracle=ppsspp target=kzl start_pc=0x08804000 steps=200000
# init r0=.. r31=.. hi=.. lo=.. f0=.. f31=.. fcr31=.. fpcond=.. v0=.. v127=.. vc0=.. vc15=..
# kernel next_uid=0x11d
# ge next_list_id=41
# mem 0x09fff000 <256 bytes as hex>     (16 lines: top 4 KB of user RAM)
```

## Comparing a run

```
python tools/kzl/ppsspp_trace.py <ISO> --steps=200000 --out=build/kzl/ref/trace_ppsspp_200k.txt
out/build/clang-cl/kzl.exe --image build/kzl/gen/kzl_image.bin 08804000 08804000 build/kzl/ref/trace_ppsspp_200k.txt build/kzl/ref/trace_recomp.txt
python external/psp-recomp/tools/tracediff.py build/kzl/ref/trace_ppsspp_200k.txt build/kzl/ref/trace_recomp.txt
```

Without `--sched` the driver runs only `module_start`, which returns after 71 steps; those steps
match PPSSPP exactly (FINDINGS F-049).

## Function-boundary audit

The call trace records each unique source, call kind, and runtime target without writing every
executed instruction. Native function replacements are disabled for both trace modes so guest
calls remain visible.

```
python tools/kzl/ppsspp_calls.py <ISO> --timeout=90 --padscript=tools/ppsspp/kzl_calltargets.pad --out=build/kzl/ref/calls_ppsspp_boot.txt
python tools/kzl/calltargets.py build/kzl/ref/calls_ppsspp_boot.txt --report=research/kzl_calltargets.txt
```

The T-2.7 capture contains 12,399 unique edges and 4,553 targets inside KZL. All executed targets
are represented by the effective 42,600-function codegen inventory; the report separately
recognizes the existing `jal .+8` get-PC override as an intentional non-function.

## Golden-frame harness

`tools/kzl/golden_frames.py` runs the patched PPSSPPHeadless software renderer and the recompiled
D3D12 runtime, requires both processes to produce the exact 50-file inventory, and invokes the
strict `external/psp-recomp/tools/ppmdiff.py` gate. The committed manifests contain no game data.
The ISO, generated image, PPSSPP executable, and savedata templates remain protected local assets.
The calibrated gate permits at most 6,000 pixels per frame whose maximum RGB-channel delta exceeds
64. This covers the known software-versus-D3D12 rasterization differences while rejecting
semantically mismatched scenes.

The frame manifest is intentionally backend-specific because PPSSPP and the standalone runtime
do not issue display flips at the same points during boot:

```
# psp-recomp golden frames v2
<ppsspp-present> <runtime-present> <stable-name.ppm> <scene>
```

It must contain exactly 50 entries with increasing indices and unique names. The required scene
labels are `boot`, `menu`, `cutscene`, `gameplay`, and `hud`.

The pad script keeps the logical button sequence shared while using PPSSPP vblanks and runtime
presentation counts. Runtime presentation timing avoids turbo-scheduler variance consuming the
script before a menu appears:

```
# psp-recomp pad script v3
<ppsspp-vblank> <runtime-present> <hex-button-mask> <ppsspp-width> <runtime-width>
```

PPSSPP widths are measured in vblanks; runtime widths are measured in presented frames.

Use separate savedata templates. PPSSPP implements the retail secure-savedata path, while the
standalone runtime currently stores the same game payload without encryption; copying one
implementation's template over the other is not reliable.

```
python tools/kzl/golden_frames.py `
  --iso D:\protected\Killzone_Liberation.iso `
  --ppsspp D:\tools\ppsspp\Windows\x64\Release\PPSSPPHeadless.exe `
  --runtime out\build\clang-cl-d3d12\kzl.exe `
  --image build\kzl\gen\kzl_image.bin `
  --ppsspp-memstick-template D:\protected\memstick-ppsspp `
  --runtime-memstick-template D:\protected\memstick-runtime `
  --threshold 64 `
  --max-threshold-pixels 6000 `
  --warp
```

Each template is copied to a temporary directory before use, so the protected baseline is never
modified. `KZL_GOLDEN_PPSSPP_MEMSTICK` and `KZL_GOLDEN_RUNTIME_MEMSTICK` provide the two defaults;
`KZL_GOLDEN_MEMSTICK` remains a legacy fallback for local experiments.

The `Golden frames` workflow runs only on the protected `kzl-golden` self-hosted Windows runner.
Configure these repository variables with runner-local paths:

- `KZL_GOLDEN_ISO`
- `KZL_GOLDEN_PPSSPP_HEADLESS`
- `KZL_GOLDEN_PPSSPP_MEMSTICK`
- `KZL_GOLDEN_RUNTIME_MEMSTICK`
- `KZL_GOLDEN_GEN_DIR`
- `KZL_GOLDEN_SDL3_DIR`
- `KZL_GOLDEN_DXC`

The workflow uploads only `ppmdiff.json` and deletes captured PPMs after every run. It never
publishes screenshots, savedata, generated game code, or other copyrighted payloads.
