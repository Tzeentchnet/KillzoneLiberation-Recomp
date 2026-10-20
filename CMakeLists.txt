# Killzone: Liberation static recompilation - build.  -> T-2.9, D4
#
# Before configuring, produce the generated C (never committed, it is derived from the game):
#   python tools/kzl/extract.py <your ISO>
#   python tools/kzl/gen.py
#
# Windows: configure with the "clang-cl" preset (CMakePresets.json). The generated code uses GNU C
# (__builtin_clz, statement expressions), which MSVC cl rejects, so clang-cl is required (F-045).
cmake_minimum_required(VERSION 3.25)
project(KZLRecomp LANGUAGES C CXX)

set(KZL_GEN_DIR "${CMAKE_SOURCE_DIR}/build/kzl/gen" CACHE PATH "Directory written by tools/kzl/gen.py")
set(PSP_RECOMP_DIR "${CMAKE_SOURCE_DIR}/external/psp-recomp" CACHE PATH "sal063 fork (submodule)")

option(KZL_ENABLE_D3D12 "Build the SDL3/D3D12 backend" OFF)
option(KZL_RUNTIME_ONLY "Compile the redistributable runtime without generated game code" OFF)
if(KZL_RUNTIME_ONLY AND KZL_ENABLE_D3D12)
  message(FATAL_ERROR "KZL_RUNTIME_ONLY currently supports the dependency-free Windows runtime only")
endif()
if(KZL_ENABLE_D3D12)
  if(NOT WIN32)
    message(FATAL_ERROR "KZL_ENABLE_D3D12 requires Windows")
  endif()
  find_package(SDL3 CONFIG REQUIRED COMPONENTS SDL3-shared)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  set(KZL_DXC_EXECUTABLE "" CACHE FILEPATH "Optional explicit path to dxc.exe")
  set(_KZL_DXC_ARGS)
  if(KZL_DXC_EXECUTABLE)
    list(APPEND _KZL_DXC_ARGS --dxc "${KZL_DXC_EXECUTABLE}")
  endif()
  add_custom_target(kzl_d3d12_shaders
    COMMAND "${Python3_EXECUTABLE}"
            "${PSP_RECOMP_DIR}/tools/compile_d3d12_shaders.py" ${_KZL_DXC_ARGS}
    VERBATIM)
  add_custom_target(kzl_d3d12_shaders_check
    COMMAND "${Python3_EXECUTABLE}"
            "${PSP_RECOMP_DIR}/tools/compile_d3d12_shaders.py" ${_KZL_DXC_ARGS} --check
    VERBATIM)
endif()

if(NOT KZL_RUNTIME_ONLY AND CMAKE_C_COMPILER_ID STREQUAL "MSVC")
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

if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")  # clang-cl
  set(KZL_FP_FLAGS /fp:precise /clang:-ffp-contract=off /clang:-fno-strict-aliasing)
else()
  set(KZL_FP_FLAGS -ffp-contract=off -fno-strict-aliasing)
endif()

if(NOT KZL_RUNTIME_ONLY)
  file(GLOB KZL_HOT_GEN_SRCS CONFIGURE_DEPENDS
       "${KZL_GEN_DIR}/kzl_recomp_hot_[0-9][0-9][0-9].c")
  file(GLOB KZL_COLD_GEN_SRCS CONFIGURE_DEPENDS
       "${KZL_GEN_DIR}/kzl_recomp_cold_[0-9][0-9][0-9].c")
  file(GLOB KZL_LEGACY_GEN_SRCS CONFIGURE_DEPENDS
       "${KZL_GEN_DIR}/kzl_recomp_[0-9][0-9][0-9].c")
  set(KZL_REGISTER_SRC "${KZL_GEN_DIR}/kzl_recomp_register.c")
  if(KZL_HOT_GEN_SRCS OR KZL_COLD_GEN_SRCS)
    if(KZL_LEGACY_GEN_SRCS)
      message(FATAL_ERROR "Mixed legacy and hot/cold generated files in ${KZL_GEN_DIR}; rerun tools/kzl/gen.py")
    endif()
    set(KZL_GEN_SRCS ${KZL_HOT_GEN_SRCS} ${KZL_COLD_GEN_SRCS} "${KZL_REGISTER_SRC}")
    set(_KZL_OPTIMIZED_SPLIT ON)
  else()
    set(KZL_GEN_SRCS ${KZL_LEGACY_GEN_SRCS} "${KZL_REGISTER_SRC}")
    set(_KZL_OPTIMIZED_SPLIT OFF)
  endif()
  if(NOT EXISTS "${KZL_REGISTER_SRC}")
    set(KZL_GEN_SRCS)
  endif()
  if(NOT KZL_GEN_SRCS)
    message(FATAL_ERROR "No generated code in ${KZL_GEN_DIR}. Run tools/kzl/extract.py <ISO> and tools/kzl/gen.py first.")
  endif()
  list(LENGTH KZL_GEN_SRCS _n)
  message(STATUS "KZL generated translation units: ${_n}")

  # Recompiled game code. Float behaviour must match the PSP: no FMA contraction, no fast-math (F-013).
  add_library(kzl_game STATIC ${KZL_GEN_SRCS})
  target_include_directories(kzl_game PRIVATE "${PSP_RECOMP_DIR}/src/rt" "${KZL_GEN_DIR}")
  if(_KZL_OPTIMIZED_SPLIT)
    if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
      set(_KZL_HOT_OPT /O2)
      set(_KZL_COLD_OPT /O1)
    else()
      set(_KZL_HOT_OPT -O2)
      set(_KZL_COLD_OPT -O1)
    endif()
    set_source_files_properties(${KZL_HOT_GEN_SRCS}
      PROPERTIES COMPILE_OPTIONS "$<$<CONFIG:Release>:${_KZL_HOT_OPT}>")
    set_source_files_properties(${KZL_COLD_GEN_SRCS} "${KZL_REGISTER_SRC}"
      PROPERTIES COMPILE_OPTIONS "$<$<CONFIG:Release>:${_KZL_COLD_OPT}>")
    list(LENGTH KZL_HOT_GEN_SRCS _hot_n)
    list(LENGTH KZL_COLD_GEN_SRCS _cold_n)
    message(STATUS "KZL generated optimization: ${_hot_n} hot TUs at O2, ${_cold_n} cold TUs at O1")
  endif()
  if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
    target_compile_options(kzl_game PRIVATE /W3 ${KZL_FP_FLAGS})
  else()
    target_compile_options(kzl_game PRIVATE -Wall -Wno-unused-label ${KZL_FP_FLAGS})
  endif()
endif()

# sal063 runtime (HLE kernel, scheduler, ISO, media, GDI window, software GE) plus its
# bring-up driver. SDL3/D3D12 is optional; SDL3/Vulkan remains outside the root build.  -> T-3.1, T-4.2
set(RT "${PSP_RECOMP_DIR}/src/rt")
set(AT3 "${PSP_RECOMP_DIR}/third_party/at3_standalone")
set(KZL_AT3_SRCS
  ${AT3}/atrac.cpp
  ${AT3}/atrac3.cpp
  ${AT3}/atrac3plus.cpp
  ${AT3}/atrac3plusdec.cpp
  ${AT3}/atrac3plusdsp.cpp
  ${AT3}/get_bits.cpp
  ${AT3}/compat.cpp
  ${AT3}/fft.cpp
  ${AT3}/mem.cpp
  ${RT}/atrac_decode.cpp)
add_library(kzl_at3 STATIC ${KZL_AT3_SRCS})
target_include_directories(kzl_at3 PRIVATE "${AT3}" "${RT}")
target_compile_features(kzl_at3 PRIVATE cxx_std_17)
if(MSVC)
  target_compile_options(kzl_at3 PRIVATE /W3 /fp:precise)
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    target_compile_options(kzl_at3 PRIVATE /clang:-ffp-contract=off)
  endif()
else()
  target_compile_options(kzl_at3 PRIVATE -Wall -Wextra -ffp-contract=off)
endif()

set(KZL_RUNTIME_SRCS
  ${RT}/recomp.c ${RT}/dispatch_table.c ${RT}/fpu_mode.c ${RT}/interp_runtime.cpp
  ${PSP_RECOMP_DIR}/src/ref/interp.cpp
  ${RT}/vfpu_interp.c ${RT}/vfpu_asin.c ${RT}/hle.c ${RT}/net.c ${RT}/kmem.c ${RT}/intr.c ${RT}/gelist.c ${RT}/callback.c ${RT}/sched.c
  ${RT}/iso.c ${RT}/mpeg.c ${RT}/pgf.c ${RT}/gui.c ${RT}/input_config.c ${RT}/startup_check.c
  ${RT}/audio_mixer.c ${RT}/audio_xaudio2.cpp ${RT}/sas_reverb.c ${RT}/h264_mf.c ${RT}/savedata.c
  ${RT}/osk_win.c ${RT}/ge.c)
if(KZL_ENABLE_D3D12)
  list(APPEND KZL_RUNTIME_SRCS
    ${RT}/gpu_d3d12/device.cpp
    ${RT}/gpu_d3d12/framebuffer.cpp
    ${RT}/gpu_d3d12/framebuffer_key.cpp
    ${RT}/gpu_d3d12/pipeline.cpp
    ${RT}/gpu_d3d12/pipeline_key.cpp
    ${RT}/gpu_d3d12/present.cpp
    ${RT}/gpu_d3d12/present_layout.cpp
    ${RT}/gpu_d3d12/shader_state.cpp
    ${RT}/gpu_d3d12/texture.cpp
    ${RT}/gpu_d3d12/texture_key.cpp
    ${RT}/gpu_d3d12/vertex.cpp)
endif()

if(KZL_RUNTIME_ONLY)
  add_library(kzl_runtime_compile STATIC ${KZL_RUNTIME_SRCS})
  add_dependencies(kzl_runtime_compile kzl_at3)
  target_include_directories(kzl_runtime_compile PRIVATE "${RT}")
  target_compile_definitions(kzl_runtime_compile PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_features(kzl_runtime_compile PRIVATE cxx_std_17)
  if(MSVC)
    target_compile_options(kzl_runtime_compile PRIVATE /W3 ${KZL_FP_FLAGS})
  else()
    target_compile_options(kzl_runtime_compile PRIVATE -Wall -Wextra ${KZL_FP_FLAGS})
  endif()
  return()
endif()

function(kzl_configure_runtime_target target)
  target_include_directories(${target} PRIVATE "${RT}")
  target_compile_definitions(${target} PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_options(${target} PRIVATE ${KZL_FP_FLAGS})
  target_link_libraries(${target} PRIVATE kzl_game kzl_at3 mfplat mfuuid gdi32 user32 dinput8 dxguid ole32 winmm xaudio2 bcrypt)
  if(KZL_ENABLE_D3D12)
    target_compile_definitions(${target} PRIVATE SR_D3D12)
    target_compile_features(${target} PRIVATE cxx_std_17)
    target_link_libraries(${target} PRIVATE SDL3::SDL3 d3d12 dxgi)
    add_custom_command(TARGET ${target} POST_BUILD
      COMMAND ${CMAKE_COMMAND} -E copy_if_different
              $<TARGET_FILE:SDL3::SDL3-shared> $<TARGET_FILE_DIR:${target}>)
  endif()
endfunction()

add_executable(kzl_driver ${RT}/driver.c ${KZL_RUNTIME_SRCS})
kzl_configure_runtime_target(kzl_driver)
target_compile_definitions(kzl_driver PRIVATE
  SR_EXPECTED_ISO_SIZE=568498176
  SR_EXPECTED_ISO_SHA1="5bc4fc8cd8d72c9c2e7c1c03a4325a29bed6e69a")
set_target_properties(kzl_driver PROPERTIES OUTPUT_NAME kzl)

include(CTest)
if(BUILD_TESTING)
  add_executable(kzl_startup_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/startup_check_test.c
    ${RT}/startup_check.c)
  target_include_directories(kzl_startup_tests PRIVATE "${RT}")
  target_compile_definitions(kzl_startup_tests PRIVATE
    _CRT_SECURE_NO_WARNINGS
    SR_EXPECTED_ISO_SIZE=3
    SR_EXPECTED_ISO_SHA1="a9993e364706816aba3e25717850c26c9cd0d89d")
  target_compile_options(kzl_startup_tests PRIVATE ${KZL_FP_FLAGS})
  target_link_libraries(kzl_startup_tests PRIVATE bcrypt)
  add_test(NAME kzl_startup_check COMMAND kzl_startup_tests)

  add_executable(kzl_audio_mixer_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/audio_mixer_test.c
    ${RT}/audio_mixer.c)
  target_include_directories(kzl_audio_mixer_tests PRIVATE "${RT}")
  target_compile_options(kzl_audio_mixer_tests PRIVATE ${KZL_FP_FLAGS})
  add_test(NAME kzl_audio_mixer COMMAND kzl_audio_mixer_tests)

  add_executable(kzl_input_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/input_config_test.c
    ${RT}/input_config.c)
  target_include_directories(kzl_input_tests PRIVATE "${RT}")
  target_compile_definitions(kzl_input_tests PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_options(kzl_input_tests PRIVATE ${KZL_FP_FLAGS})
  add_test(NAME kzl_input_config COMMAND kzl_input_tests)

  add_executable(kzl_dispatch_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/dispatch_table_test.c
    ${RT}/dispatch_table.c)
  target_include_directories(kzl_dispatch_tests PRIVATE "${RT}")
  target_compile_options(kzl_dispatch_tests PRIVATE ${KZL_FP_FLAGS})
  add_test(NAME kzl_dispatch_table COMMAND kzl_dispatch_tests)

  add_executable(kzl_fpu_mode_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/fpu_mode_test.c
    ${RT}/fpu_mode.c)
  target_include_directories(kzl_fpu_mode_tests PRIVATE "${RT}")
  target_compile_options(kzl_fpu_mode_tests PRIVATE ${KZL_FP_FLAGS})
  add_test(NAME kzl_fpu_mode COMMAND kzl_fpu_mode_tests)

  add_executable(kzl_interp_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/interp_fallback_test.cpp
    ${RT}/recomp.c
    ${RT}/dispatch_table.c
    ${RT}/fpu_mode.c
    ${RT}/interp_runtime.cpp
    ${PSP_RECOMP_DIR}/src/ref/interp.cpp)
  target_include_directories(kzl_interp_tests PRIVATE
    "${RT}" "${PSP_RECOMP_DIR}/src/ref")
  target_compile_definitions(kzl_interp_tests PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_features(kzl_interp_tests PRIVATE cxx_std_17)
  target_compile_options(kzl_interp_tests PRIVATE ${KZL_FP_FLAGS})
  add_test(NAME kzl_interpreter_fallback COMMAND kzl_interp_tests)

  add_executable(kzl_hle_tests EXCLUDE_FROM_ALL tools/tests/hle_smoke.c ${KZL_RUNTIME_SRCS})
  kzl_configure_runtime_target(kzl_hle_tests)
  add_test(NAME kzl_hle_smoke COMMAND kzl_hle_tests)
  if(KZL_ENABLE_D3D12)
    add_executable(kzl_d3d12_vertex_tests EXCLUDE_FROM_ALL
      ${PSP_RECOMP_DIR}/tools/tests/d3d12_vertex_test.cpp
      ${RT}/gpu_d3d12/framebuffer_key.cpp
      ${RT}/gpu_d3d12/pipeline_key.cpp
      ${RT}/gpu_d3d12/present_layout.cpp
      ${RT}/gpu_d3d12/shader_state.cpp
      ${RT}/gpu_d3d12/texture_key.cpp
      ${RT}/gpu_d3d12/vertex.cpp)
    target_include_directories(kzl_d3d12_vertex_tests PRIVATE "${RT}")
    target_compile_definitions(kzl_d3d12_vertex_tests PRIVATE SR_D3D12)
    target_compile_features(kzl_d3d12_vertex_tests PRIVATE cxx_std_17)
    target_compile_options(kzl_d3d12_vertex_tests PRIVATE ${KZL_FP_FLAGS})
    target_link_libraries(kzl_d3d12_vertex_tests PRIVATE d3d12)
    add_test(NAME kzl_d3d12_vertex COMMAND kzl_d3d12_vertex_tests)
  endif()
endif()
