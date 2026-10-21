# Twin-stick control research and API notes

Date: 2026-10-20

Target: Killzone: Liberation UCUS-98646 v1.20, loaded at `0x08804000`.
Every game address below applies only to the target pinned in
[`config/kzl.toml`](../config/kzl.toml).

## Summary

The game still contains a hidden alternate movement mode and a broader,
mostly unused controller-profile API. The surviving mode is named
`EnableDPadMovement`; it changes on-foot and several contextual controllers
from the analog movement vector to four digital movement actions.

This is probably the source of the twin-stick rumor, but it is not a complete
native twin-stick implementation:

- the PSP input backend supplies one analog pair, `Lx/Ly`;
- the game profile stores exactly two axis mappings;
- gameplay selects either analog movement or digital D-pad movement;
- no second continuous aim vector is delivered to the player controller; and
- the PC runtime currently discards right-stick axes.

A gamepad-only experiment is still worthwhile. The cheapest test is to enable
the hidden D-pad movement mode, synthesize PSP D-pad directions from the host
left stick, and send the host right stick through the PSP analog pair. If that
does not independently rotate the player's aim, a real implementation will
need a native second-stick side channel and a targeted player-controller hook.

## Confidence labels

- **Confirmed**: read directly from the supported executable, generated code,
  initialized RAM, shipped game data, or the current runtime.
- **Likely**: strongly implied by layout and call-site behavior, but not yet
  verified in an interactive gameplay experiment.
- **Hypothesis**: a proposed explanation or implementation path that still
  needs testing.

## PSP controller input path

### Imported controller functions - Confirmed

The game imports only three `sceCtrl` functions:

| Stub | NID | Function |
|---|---:|---|
| `0x08D8EE80` | `0x1F4011E6` | `sceCtrlSetSamplingMode` |
| `0x08D8EE88` | `0x3A622550` | `sceCtrlPeekBufferPositive` |
| `0x08D8EE90` | `0x6A2774F3` | `sceCtrlSetSamplingCycle` |

The canonical import list is
[`research/kzl_imports.toml`](../research/kzl_imports.toml).

The three imports are called from the PSP joystick implementation around
`0x08A75D34`-`0x08A76044`.

### Game-side sample conversion - Confirmed

`0x08A75DE4` is the controller polling routine. It:

1. peeks up to ten 16-byte `SceCtrlData` samples;
2. retains the newest sample;
3. converts byte `Lx` and `Ly` to normalized floats;
4. applies per-axis dead-zone thresholds;
5. writes one X/Y pair to the engine input state; and
6. expands PSP button bits into individual button bytes.

The routine reads only sample bytes 8 and 9, the PSP `Lx/Ly` fields. There are
no reads for an `Rx/Ry` pair.

`0x08832D20` aggregates the result into the engine joystick state. It stores:

- normalized X at joystick offset `0x1C`;
- normalized, inverted Y at offset `0x20`; and
- the physical button states beginning at offset `0x08`.

This is one two-dimensional continuous vector.

### Runtime HLE shape - Confirmed

The recomp runtime models a controller sample as:

```c
typedef struct {
    uint32_t btn;
    uint8_t lx;
    uint8_t ly;
} CtrlSample;
```

See [`external/psp-recomp/src/rt/hle.c`](../external/psp-recomp/src/rt/hle.c).
The ring buffer and `SceCtrlData` writer preserve the PSP ABI, so they must not
be extended with host-only right-stick fields.

## Controller profile API

The stripped executable retains reflected `PlayerProfile` methods for
controller remapping and preset selection. Their initialized metadata was
resolved from the live RAM dump, then each implementation was checked in the
generated code.

| Reflected API | Implementation | Backing data |
|---|---:|---|
| `SetFunctionButton(index, button)` | `0x0883913C` | `+0x03D4 + index * 4` |
| `GetFunctionButton(index)` | `0x08839178` | `+0x03D4 + index * 4` |
| `SetFunctionAxis(index, axis)` | `0x08839190` | `+0x04A0 + index * 4` |
| `GetFunctionAxis(index)` | `0x088391BC` | `+0x04A0 + index * 4` |
| `SetControllerOnFootPresetId(id)` | `0x088391D4` | `+0x04A8` |
| `GetControllerOnFootPresetId()` | `0x088391F8` | `+0x04A8` |
| `SetControllerLandVehiclePresetId(id)` | `0x08839204` | `+0x04AC` |
| `GetControllerLandVehiclePresetId()` | `0x08839228` | `+0x04AC` |
| `EnableDPadMovement(enabled)` | `0x0883812C` | remaps buttons and writes `+0x04B0` |
| `DoDPadMovement()` | `0x088381C8` | reads `+0x04B0` |

### Profile layout - Confirmed

The contiguous control-related part of the profile is:

| Offset | Shape | Purpose |
|---:|---|---|
| `0x03D4` | 51 x `int32` | game function to button mapping |
| `0x04A0` | 2 x `int32` | function-axis mapping |
| `0x04A8` | `int32` | on-foot preset ID |
| `0x04AC` | `int32` | land-vehicle preset ID |
| `0x04B0` | `uint8` | D-pad movement enabled |

`SetFunctionButton` bounds-checks its index against 51. The axis table begins
immediately after those 51 entries, and the preset fields begin immediately
after two axis entries. There is therefore no hidden storage for another
continuous `Rx/Ry` pair.

`0x08837A44` installs these relevant defaults:

```text
functionAxis[0] = 0
functionAxis[1] = 1
onFootPresetId = 1
landVehiclePresetId = 1
dPadMovement = false
```

The preset IDs survive in the save/profile shape, but no shipped options page
or game-data script was found that exposes them.

## Hidden D-pad movement mode

### Remapping behavior - Confirmed

Calling `EnableDPadMovement(true)` changes these function-to-button mappings:

| Function ID | Button ID |
|---:|---:|
| 3 | 19 |
| 7 | 18 |
| 8 | 17 |
| 9 | 16 |
| 13 | 18 |
| 41 | 2 |
| 42 | 3 |
| 43 | 1 |
| 44 | 0 |
| 45 | 18 |
| 46 | 19 |
| 47 | 17 |
| 48 | 16 |

It then sets the profile byte at `+0x04B0`. Calling it with false reinstalls
the normal mapping table.

Button IDs 0-15 are the physical PSP-style button slots. IDs 16-19 behave as
virtual directions derived from the analog input - **Likely**, based on the
joystick-state layout and the remapping above.

### Movement-vector selection - Confirmed

The shared input helpers are:

- `0x089BA1BC`: reads the two profile axis mappings and returns the normalized
  analog X/Y vector.
- `0x089BA290`: tests digital function IDs 41-44 and constructs X/Y components
  in the range `-1`, `0`, or `1`.

Several gameplay controllers read the `+0x04B0` flag and select one helper or
the other. Confirmed call sites include:

- `0x0885E21C`;
- `0x088672F4`;
- `0x088FFBD8`, in the `SoldierJoystickController` path; and
- `0x0890BCB0`, in the `LandVehicleJoystickController` path.

The important detail is that this is a source selection:

```text
movement = dPadMovement ? digitalMovement() : analogMovement()
```

It does not return both vectors. Static tracing found no second continuous
axis read in the on-foot soldier controller.

### Script exposure and missing UI - Confirmed

The executable also exposes:

| Game script API | Implementation |
|---|---:|
| `IsDPadMovementEnabled` | `0x0899C088` |
| `EnableDPadMovement` | `0x0899C100` |

The shipped `PSP.DAT` resources contain no call to either name. The offline
debug options page contains a Controls button, but its `GotToControls`
callback is empty. This is evidence of an unfinished or removed controls
surface, not proof of a removed twin-stick implementation.

The same broad control/profile strings are present in both v1.00 and v1.20.
Neither executable contains a `SV_PAD_RIGHT_ANALOG` counterpart to the
existing `SV_PAD_LEFT_ANALOG` string.

## Current native runtime limitations

The native runtime currently preserves the PSP's one-stick model on every
presenter:

- [`external/psp-recomp/src/rt/gpu_d3d12/device.cpp`](../external/psp-recomp/src/rt/gpu_d3d12/device.cpp)
  reads only `SDL_GAMEPAD_AXIS_LEFTX` and `SDL_GAMEPAD_AXIS_LEFTY`.
- [`external/psp-recomp/src/rt/gpu_sdl3vk/sdl3vk.c`](../external/psp-recomp/src/rt/gpu_sdl3vk/sdl3vk.c)
  does the same.
- [`external/psp-recomp/src/rt/gui.c`](../external/psp-recomp/src/rt/gui.c)
  declares XInput `sThumbRX/sThumbRY`, but copies only `sThumbLX/sThumbLY`
  into the live pad state. Its DirectInput path also normalizes only X and Y.
- [`external/psp-recomp/src/rt/input_config.h`](../external/psp-recomp/src/rt/input_config.h)
  has one set of analog directions and one analog transform.

`SR_PAD_RIGHT_STICK` is the right-stick click button. It does not represent
right-stick axes.

## Verdict

### Native hidden twin-stick mode

**Not found.**

The game contains one continuous input vector, not separate movement and aim
vectors. The hidden mode replaces analog movement with digital movement but
does not add another axis pair.

### Hidden alternate controls

**Confirmed.**

D-pad movement, reflected remapping methods, profile preset IDs, and gameplay
branches that honor the D-pad flag all remain in the executable.

### Native recomp enhancement

**Feasible, but still experimental.**

The hidden mode offers a useful first test because it can move locomotion away
from the PSP analog pair. Whether the remaining analog direction affects
on-foot aim in a useful way must be verified interactively. Static evidence
suggests a complete implementation will probably need a targeted aim/facing
hook.

## Proposed experiment

The experiment must be opt-in and default off so baseline behavior and
protected captures remain unchanged.

### Stage 1 implementation status

The host-side Stage 1 experiment is now implemented behind
`twin_stick.enabled = false` in `input.ini`:

- SDL, XInput, and DirectInput presenters capture movement and aim sticks;
- the shared input policy applies independent radial transforms;
- movement is converted to PSP D-pad bits with hysteresis;
- aim is retained in a native host-side vector as well as the PSP `Lx/Ly`
  compatibility path; and
- the hidden profile mappings are overlaid in memory without setting the
  profile dirty flag, then restored when the controller disconnects.

The implementation intentionally leaves `SceCtrlData` unchanged.

Interactive testing on 2026-10-20 confirmed the Stage 1 stop condition: the
left stick moved the player through the hidden D-pad mode, but the right stick
had no observable effect. No timing or alternate-frame workaround was added.

The current Stage 2 experiment carries the transformed aim vector through a
native side channel. A generated instruction hook at `0x08900688`, inside
`SoldierJoystickController`, replaces the base facing vector at controller
offset `+0x114` immediately before the original target and auto-aim correction.
Centered aim leaves the original vector untouched. On-foot gameplay validation
of this second-vector path is still required.

`input.ini` changes are polled during presentation and hot-reloaded after an
atomic controller-dialog save. Invalid replacements are rejected without
discarding the last valid mappings or active twin-stick policy.

### Stage 1: test the surviving hidden mode

1. Capture both host gamepad sticks in the Win32, D3D12, and Vulkan paths.
2. Apply independent radial transforms to the movement and aim sticks.
3. Convert the host left stick into PSP D-pad bits with a dead zone and
   hysteresis.
4. Send the host right stick as the PSP `Lx/Ly` pair.
5. Enable the game's hidden D-pad movement mapping after the player profile is
   available.
6. Do not change the guest `SceCtrlData` layout.

Initial scope should be gamepad-only. Mouse aiming and keyboard emulation can
follow after the gameplay behavior is proven.

### Stage 1 success criteria

In an on-foot mission:

- left stick moves the player with the right stick centered;
- right stick rotates or selects aim direction with the left stick centered;
- both sticks work simultaneously without alternating or stuttering;
- fire direction follows the right stick rather than movement;
- strafe lock, dodge, cover, grenades, reload, interaction, and buddy commands
  remain usable;
- menus remain navigable; and
- disabling the experiment restores byte-for-byte baseline input behavior.

### Stage 1 stop condition

If the right stick does not independently affect on-foot aim while hidden
D-pad movement is enabled, do not add timing hacks or alternate-frame input.
Proceed to a real second-vector design.

## Second-vector design if Stage 1 fails

### Host-side API

Use semantic movement/aim names rather than physical left/right names so
future remapping is possible:

```c
typedef struct SrInputSticks {
    int movement_x;
    int movement_y;
    int aim_x;
    int aim_y;
} SrInputSticks;
```

The presenter should return raw signed host axes. Shared input policy should
apply dead zones, curves, inversion, and clamping once.

Suggested configuration shape:

```ini
twin_stick.enabled = false
movement.deadzone = 0.24
movement.curve = 1.0
aim.deadzone = 0.24
aim.curve = 1.0
aim.invert_x = false
aim.invert_y = false
```

Exact names remain a design decision. An untouched existing `input.ini` must
retain current behavior.

### Guest integration

Keep PSP controller samples unchanged. Carry the host-only aim vector through
a native runtime side channel, then hook the narrowest recovered
`SoldierJoystickController` point that separates locomotion from facing or
weapon aim.

The hook must:

- affect only supported player-controlled contexts;
- preserve auto-aim and object-aim behavior;
- fall back to original behavior when the aim stick is centered;
- avoid writing new fields into guest-owned objects unless their layout is
  fully understood; and
- fail explicitly if the expected target addresses or object state are not
  present.

Mounted guns and land vehicles should remain on the original input path until
their semantics are tested separately.

## Save-data precautions

`EnableDPadMovement` modifies the profile and marks it dirty. The first
experiment should not silently persist control changes into a user's PSP save.
Use an isolated save directory and either:

- apply the alternate mappings after profile load without marking the profile
  dirty; or
- restore the original values before any save operation.

Do not change the serialized profile layout.

## Validation matrix

| Area | Required check |
|---|---|
| Feature disabled | Existing input tests and protected frame path remain unchanged |
| Input policy | Independent stick dead zones, curves, inversion, and diagonal clamping |
| D-pad synthesis | Stable cardinal/diagonal transitions with hysteresis |
| On-foot movement | Walk, run, strafe lock, dodge, cover, collision |
| On-foot aim | Independent facing, fire direction, auto-aim, object aim |
| Weapons | Fire, reload, grenades, placed weapons |
| Context changes | Enter/exit mounted gun, vehicle, ladder, vault, menus |
| Save/profile | No unintended persistence or profile corruption |
| Backends | D3D12 SDL, Vulkan SDL, Win32 XInput, DirectInput |
| Non-gamepad input | Existing keyboard and mouse mappings remain intact |

## Reproducing the key disassembly

Generated game code and RAM dumps are local, ignored artifacts and must not be
committed. After extracting the supported image and running generation, the
key routines can be inspected with:

```powershell
python tools\kzl\mipsdis.py `
  build\kzl\disc\KZL.PRX 08a75de4 08a76044 --base=08804000

python tools\kzl\mipsdis.py `
  build\kzl\disc\KZL.PRX 08837a44 08837b58 --base=08804000

python tools\kzl\mipsdis.py `
  build\kzl\disc\KZL.PRX 0883812c 088381d4 --base=08804000

python tools\kzl\mipsdis.py `
  build\kzl\disc\KZL.PRX 0883913c 08839234 --base=08804000

python tools\kzl\mipsdis.py `
  build\kzl\disc\KZL.PRX 089ba1bc 089ba338 --base=08804000
```

The generated translation units that contain the corresponding routines are:

- `build/kzl/gen/kzl_recomp_hot_015.c`: PSP polling;
- `build/kzl/gen/kzl_recomp_hot_003.c`: joystick aggregation;
- `build/kzl/gen/kzl_recomp_hot_004.c`: default mapping table;
- `build/kzl/gen/kzl_recomp_cold_007.c`: profile APIs and D-pad toggle; and
- `build/kzl/gen/kzl_recomp_cold_082.c`: analog and digital movement helpers.

These files are derived from the user-supplied executable and remain ignored.
