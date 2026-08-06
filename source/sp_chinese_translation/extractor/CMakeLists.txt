cmake_minimum_required(VERSION 3.21)
project(sp_translation_extractor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(HDF5 CONFIG REQUIRED)
# CMake's FindLibArchive may prefer vcpkg's debug archive in a multi-config
# build. Pin the release library so the standalone EXE never mixes CRTs.
if(MSVC AND DEFINED VCPKG_INSTALLED_DIR AND DEFINED VCPKG_TARGET_TRIPLET)
    set(LibArchive_LIBRARY
        "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/lib/archive.lib"
        CACHE FILEPATH "libarchive release library" FORCE)
endif()
find_package(LibArchive REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(pugixml CONFIG REQUIRED)

add_executable(sp_translation_extractor main.cpp)
target_link_libraries(sp_translation_extractor PRIVATE
    hdf5::hdf5-static
    LibArchive::LibArchive
    nlohmann_json::nlohmann_json
    pugixml::pugixml
)
target_compile_definitions(sp_translation_extractor PRIVATE
    UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
if(MSVC)
    target_compile_options(sp_translation_extractor PRIVATE
        /W4 /WX /utf-8 /permissive- /Zc:__cplusplus)
    set_property(TARGET sp_translation_extractor PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
