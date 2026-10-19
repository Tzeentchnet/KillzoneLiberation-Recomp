# PPSSPP oracle with psp-recomp traces

`psprecomp-trace.patch` makes PPSSPPHeadless write the per-instruction trace format of the
psp-recomp toolkit (`external/psp-recomp/tools/TRACE_FORMAT.md`), so a run of PPSSPP's
interpreter can be diffed against our recompiled code with `tools/tracediff.py`.
It applies to PPSSPP **v1.20.4** and touches four files:

- `Core/MIPS/MIPSTables.cpp`: the trace writer in the interpreter's checked loop.
- `Core/HLE/sceKernel.h`: a read-only accessor for the next kernel object handle.
- `Core/HLE/sceCtrl.cpp`: optional frame-based scripted controller input for reproducible UI paths.
- `headless/Headless.cpp`: turns off function replacements while tracing (they skip guest
  instructions). The 0xDEADBEEF filling after HLE calls stays on, because the psp-recomp
  runtime reproduces it.

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
| `PSPRECOMP_PADSCRIPT` | optional input file; each line is `<vblank> <hex PSP button mask> <width in vblanks>` |

Run with the interpreter (`-i`). The JIT never reaches the traced loop. When the trace is complete
the build writes `<trace>.done`, which `ppsspp_trace.py` uses to stop the emulator.

## Trace header

Before step 0 the trace carries the state the recompiled run must start from. The fork's
`src/rt/driver.c` (`kzl.exe --image ...`) reads all of it:

```
# psp-recomp trace v1 oracle=ppsspp target=kzl start_pc=0x08804000 steps=200000
# init r0=.. r31=.. hi=.. lo=.. f0=.. f31=.. fcr31=.. fpcond=.. v0=.. v127=.. vc0=.. vc15=..
# kernel next_uid=0x11d
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
