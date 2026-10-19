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

# Recompiled game code. Float behaviour must match the PSP: no FMA contraction, no fast-math (F-013).
add_library(kzl_game STATIC ${KZL_GEN_SRCS})
target_include_directories(kzl_game PRIVATE "${PSP_RECOMP_DIR}/src/rt" "${KZL_GEN_DIR}")
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")  # clang-cl
  target_compile_options(kzl_game PRIVATE /W3 /fp:precise /clang:-ffp-contract=off /clang:-fno-strict-aliasing)
else()
  target_compile_options(kzl_game PRIVATE -Wall -Wno-unused-label -ffp-contract=off -fno-strict-aliasing)
endif()
