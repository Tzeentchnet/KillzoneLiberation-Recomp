# Killzone: Liberation static recompilation - build.  -> T-2.9, D4
#
# Before configuring, produce the generated C (never committed, it is derived from the game):
#   python tools/kzl/extract.py <your ISO>
#   python tools/kzl/gen.py
#
# Windows: configure with the "clang-cl" preset (CMakePresets.json). The generated code uses GNU C
# (__builtin_clz, statement expressions), which MSVC cl rejects, so clang-cl is required (F-045).
cmake_minimum_required(VERSION 3.25)
project(KZLRecomp LANGUAGES C)

set(KZL_GEN_DIR "${CMAKE_SOURCE_DIR}/build/kzl/gen" CACHE PATH "Directory written by tools/kzl/gen.py")
set(PSP_RECOMP_DIR "${CMAKE_SOURCE_DIR}/external/psp-recomp" CACHE PATH "sal063 fork (submodule)")

file(GLOB KZL_GEN_SRCS CONFIGURE_DEPENDS
     "${KZL_GEN_DIR}/kzl_recomp_[0-9][0-9][0-9].c"
     "${KZL_GEN_DIR}/kzl_recomp_register.c")
if(NOT KZL_GEN_SRCS)
  message(FATAL_ERROR "No generated code in ${KZL_GEN_DIR}. Run tools/kzl/extract.py <ISO> and tools/kzl/gen.py first.")
endif()
list(LENGTH KZL_GEN_SRCS _n)
message(STATUS "KZL generated translation units: ${_n}")

if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "MSVC cl cannot compile the generated GNU C; configure with clang-cl (preset 'clang-cl').")
endif()
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  get_filename_component(KZL_CLANG_BIN_DIR "${CMAKE_C_COMPILER}" DIRECTORY)
  set(KZL_LLVM_LIB "${KZL_CLANG_BIN_DIR}/llvm-lib.exe")
  if(NOT EXISTS "${KZL_LLVM_LIB}")
    message(FATAL_ERROR "clang-cl requires llvm-lib.exe next to the compiler: ${KZL_LLVM_LIB}")
  endif()
  set(CMAKE_AR "${KZL_LLVM_LIB}")
endif()

# Recompiled game code. Float behaviour must match the PSP: no FMA contraction, no fast-math (F-013).
add_library(kzl_game STATIC ${KZL_GEN_SRCS})
target_include_directories(kzl_game PRIVATE "${PSP_RECOMP_DIR}/src/rt" "${KZL_GEN_DIR}")
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")  # clang-cl
  set(KZL_FP_FLAGS /fp:precise /clang:-ffp-contract=off /clang:-fno-strict-aliasing)
  target_compile_options(kzl_game PRIVATE /W3 ${KZL_FP_FLAGS})
else()
  set(KZL_FP_FLAGS -ffp-contract=off -fno-strict-aliasing)
  target_compile_options(kzl_game PRIVATE -Wall -Wno-unused-label ${KZL_FP_FLAGS})
endif()

# sal063 runtime (HLE kernel, scheduler, ISO, media, GDI window, software GE) plus its
# bring-up driver, without the SDL3/Vulkan backend (SR_SDL3VK unset). The D3D12 backend
# replaces that later (phase 4).  -> T-3.1
set(RT "${PSP_RECOMP_DIR}/src/rt")
set(KZL_RUNTIME_SRCS
  ${RT}/recomp.c ${RT}/vfpu_interp.c ${RT}/vfpu_asin.c ${RT}/hle.c ${RT}/net.c ${RT}/kmem.c ${RT}/intr.c ${RT}/gelist.c ${RT}/callback.c ${RT}/sched.c
  ${RT}/iso.c ${RT}/mpeg.c ${RT}/pgf.c ${RT}/gui.c ${RT}/audio.c ${RT}/h264_mf.c ${RT}/savedata.c
  ${RT}/osk_win.c ${RT}/ge.c)

function(kzl_configure_runtime_target target)
  target_include_directories(${target} PRIVATE "${RT}")
  target_compile_definitions(${target} PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_options(${target} PRIVATE ${KZL_FP_FLAGS})
  target_link_libraries(${target} PRIVATE kzl_game mfplat mfuuid gdi32 user32 dinput8 dxguid ole32 winmm)
endfunction()

add_executable(kzl_driver ${RT}/driver.c ${KZL_RUNTIME_SRCS})
kzl_configure_runtime_target(kzl_driver)
set_target_properties(kzl_driver PROPERTIES OUTPUT_NAME kzl)

include(CTest)
if(BUILD_TESTING)
  add_executable(kzl_hle_tests EXCLUDE_FROM_ALL tools/tests/hle_smoke.c ${KZL_RUNTIME_SRCS})
  kzl_configure_runtime_target(kzl_hle_tests)
  add_test(NAME kzl_hle_smoke COMMAND kzl_hle_tests)
endif()
