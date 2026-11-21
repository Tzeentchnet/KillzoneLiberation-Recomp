cmake_minimum_required(VERSION 3.25)

foreach(required
    APP_BUNDLE EXECUTABLE INFO_PLIST GAME_IMAGE ASSETS_DIR FONT_DIR
    SDL_LIBRARY VULKAN_LIBRARY MOLTENVK_LIBRARY
    SDL_LICENSE VULKAN_LICENSE MOLTENVK_LICENSE ICD_FILE ICON_FILE)
  if(NOT DEFINED ${required} OR "${${required}}" STREQUAL "")
    message(FATAL_ERROR "package_app: ${required} is required")
  endif()
endforeach()

foreach(required_file
    EXECUTABLE INFO_PLIST GAME_IMAGE SDL_LIBRARY VULKAN_LIBRARY
    MOLTENVK_LIBRARY SDL_LICENSE VULKAN_LICENSE MOLTENVK_LICENSE
    ICD_FILE ICON_FILE)
  if(NOT EXISTS "${${required_file}}")
    message(FATAL_ERROR
      "package_app: ${required_file} does not exist: ${${required_file}}")
  endif()
endforeach()

set(contents "${APP_BUNDLE}/Contents")
set(macos "${contents}/MacOS")
set(frameworks "${contents}/Frameworks")
set(resources "${contents}/Resources")
set(licenses "${resources}/Licenses")

file(REMOVE_RECURSE "${APP_BUNDLE}")
file(MAKE_DIRECTORY
  "${macos}" "${frameworks}" "${resources}/vulkan/icd.d" "${licenses}")
file(COPY_FILE "${EXECUTABLE}" "${macos}/kzl")
file(COPY_FILE "${INFO_PLIST}" "${contents}/Info.plist")
file(COPY_FILE "${GAME_IMAGE}" "${resources}/kzl_image.bin")
file(COPY_FILE "${ICON_FILE}" "${resources}/KillzoneLiberation.icns")
file(COPY "${ASSETS_DIR}" DESTINATION "${resources}")
file(COPY "${FONT_DIR}" DESTINATION "${resources}")
file(COPY_FILE
  "${SDL_LIBRARY}" "${frameworks}/libSDL3.0.dylib")
file(COPY_FILE
  "${VULKAN_LIBRARY}" "${frameworks}/libvulkan.1.dylib")
file(COPY_FILE
  "${MOLTENVK_LIBRARY}" "${frameworks}/libMoltenVK.dylib")
file(COPY_FILE
  "${ICD_FILE}" "${resources}/vulkan/icd.d/MoltenVK_icd.json")
file(COPY_FILE "${SDL_LICENSE}" "${licenses}/SDL3.txt")
file(COPY_FILE "${VULKAN_LICENSE}" "${licenses}/Vulkan-Loader.txt")
file(COPY_FILE "${MOLTENVK_LICENSE}" "${licenses}/MoltenVK.txt")

function(read_install_name library output)
  execute_process(
    COMMAND otool -D "${library}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE names
    ERROR_VARIABLE failure)
  if(NOT result EQUAL 0)
    message(FATAL_ERROR "package_app: otool -D failed: ${failure}")
  endif()
  string(REPLACE "\r\n" "\n" names "${names}")
  string(REPLACE "\n" ";" lines "${names}")
  list(LENGTH lines count)
  if(count LESS 2)
    message(FATAL_ERROR
      "package_app: no install name reported for ${library}")
  endif()
  list(GET lines 1 name)
  string(STRIP "${name}" name)
  set(${output} "${name}" PARENT_SCOPE)
endfunction()

function(run_tool)
  execute_process(
    COMMAND ${ARGV}
    RESULT_VARIABLE result
    OUTPUT_VARIABLE output
    ERROR_VARIABLE failure)
  if(NOT result EQUAL 0)
    string(JOIN " " command ${ARGV})
    message(FATAL_ERROR
      "package_app: ${command} failed:\n${output}${failure}")
  endif()
endfunction()

read_install_name("${SDL_LIBRARY}" sdl_install_name)
read_install_name("${VULKAN_LIBRARY}" vulkan_install_name)

execute_process(
  COMMAND otool -l "${macos}/kzl"
  RESULT_VARIABLE load_commands_result
  OUTPUT_VARIABLE load_commands
  ERROR_VARIABLE load_commands_error)
if(NOT load_commands_result EQUAL 0)
  message(FATAL_ERROR
    "package_app: cannot inspect executable RPATHs: ${load_commands_error}")
endif()
foreach(package_rpath /opt/homebrew/lib /usr/local/lib)
  if(load_commands MATCHES "path ${package_rpath} ")
    run_tool(
      install_name_tool -delete_rpath "${package_rpath}" "${macos}/kzl")
  endif()
endforeach()

run_tool(
  install_name_tool
  -change "${sdl_install_name}" "@rpath/libSDL3.0.dylib"
  -change "${vulkan_install_name}" "@rpath/libvulkan.1.dylib"
  -add_rpath "@executable_path/../Frameworks"
  "${macos}/kzl")
run_tool(
  install_name_tool -id "@rpath/libSDL3.0.dylib"
  "${frameworks}/libSDL3.0.dylib")
run_tool(
  install_name_tool -id "@rpath/libvulkan.1.dylib"
  "${frameworks}/libvulkan.1.dylib")
run_tool(
  install_name_tool -id "@rpath/libMoltenVK.dylib"
  "${frameworks}/libMoltenVK.dylib")

execute_process(
  COMMAND otool -L "${macos}/kzl"
  RESULT_VARIABLE dependency_result
  OUTPUT_VARIABLE dependencies
  ERROR_VARIABLE dependency_error)
if(NOT dependency_result EQUAL 0)
  message(FATAL_ERROR
    "package_app: cannot inspect app dependencies: ${dependency_error}")
endif()
if(dependencies MATCHES "/opt/homebrew|/usr/local")
  message(FATAL_ERROR
    "package_app: app executable still references a package-manager path:\n"
    "${dependencies}")
endif()
execute_process(
  COMMAND otool -l "${macos}/kzl"
  RESULT_VARIABLE rpath_result
  OUTPUT_VARIABLE rpaths
  ERROR_VARIABLE rpath_error)
if(NOT rpath_result EQUAL 0)
  message(FATAL_ERROR
    "package_app: cannot audit app RPATHs: ${rpath_error}")
endif()
if(rpaths MATCHES "/opt/homebrew|/usr/local")
  message(FATAL_ERROR
    "package_app: app executable still contains a package-manager RPATH")
endif()

file(GLOB_RECURSE bundle_files
  LIST_DIRECTORIES FALSE RELATIVE "${APP_BUNDLE}" "${APP_BUNDLE}/*")
foreach(bundle_file IN LISTS bundle_files)
  string(TOLOWER "${bundle_file}" lower_file)
  if(lower_file MATCHES "\\.(iso|cso|pbp|prx|elf)$")
    message(FATAL_ERROR
      "package_app: prohibited game payload in bundle: ${bundle_file}")
  endif()
endforeach()

foreach(sign_target
    "${frameworks}/libSDL3.0.dylib"
    "${frameworks}/libvulkan.1.dylib"
    "${frameworks}/libMoltenVK.dylib"
    "${macos}/kzl")
  run_tool(codesign --force --sign - --timestamp=none "${sign_target}")
endforeach()
run_tool(
  codesign --force --deep --sign - --timestamp=none "${APP_BUNDLE}")
run_tool(codesign --verify --deep --strict "${APP_BUNDLE}")

message(STATUS "Created self-contained local app: ${APP_BUNDLE}")
