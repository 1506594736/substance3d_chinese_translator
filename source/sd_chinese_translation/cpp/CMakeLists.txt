cmake_minimum_required(VERSION 3.21)
project(sd_chinese_translation_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(QT6_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../public/sdks/qt/6.5.3/msvc2019_64")
add_library(sd_translation_delegate_qt6 SHARED translation_ui_delegate.cpp)
target_include_directories(sd_translation_delegate_qt6 PRIVATE
    "${QT6_ROOT}/include"
    "${QT6_ROOT}/include/QtCore"
    "${QT6_ROOT}/include/QtGui"
    "${QT6_ROOT}/include/QtWidgets"
    "${QT6_ROOT}/mkspecs/win32-msvc"
)
target_link_libraries(sd_translation_delegate_qt6 PRIVATE
    "${QT6_ROOT}/lib/Qt6Core.lib"
    "${QT6_ROOT}/lib/Qt6Gui.lib"
    "${QT6_ROOT}/lib/Qt6Widgets.lib"
)
target_compile_definitions(sd_translation_delegate_qt6 PRIVATE
    QT_CORE_LIB QT_GUI_LIB QT_WIDGETS_LIB UNICODE _UNICODE
    SD_TRANSLATION_DESIGNER=1)
if(MSVC)
    target_compile_options(sd_translation_delegate_qt6 PRIVATE
        /W4 /WX /Zc:__cplusplus /permissive- /utf-8)
endif()
set_target_properties(sd_translation_delegate_qt6 PROPERTIES
    OUTPUT_NAME "sd_translation_delegate_qt6"
    PREFIX ""
)

# Standalone term extractor shared with the Painter plug-in. It has no Python
# or host-application dependency, so the same parser implementation is used by
# both products while each package receives a product-specific executable name.
set(SD_DEPS_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../public/sdks/deps")
set(SHARED_EXTRACTOR_SOURCE
    "${CMAKE_CURRENT_SOURCE_DIR}/../../sp_chinese_translation/cpp/extractor.cpp")
if(NOT EXISTS "${SD_DEPS_ROOT}/lib/archive.lib")
    message(FATAL_ERROR "Bundled extractor dependencies are missing: ${SD_DEPS_ROOT}")
endif()
if(NOT EXISTS "${SHARED_EXTRACTOR_SOURCE}")
    message(FATAL_ERROR "Shared extractor source is missing")
endif()

add_executable(sd_translation_extractor "${SHARED_EXTRACTOR_SOURCE}")
target_include_directories(sd_translation_extractor PRIVATE
    "${SD_DEPS_ROOT}/include"
)
target_link_libraries(sd_translation_extractor PRIVATE
    "${SD_DEPS_ROOT}/lib/libhdf5.lib"
    "${SD_DEPS_ROOT}/lib/archive.lib"
    "${SD_DEPS_ROOT}/lib/szip-static.lib"
    "${SD_DEPS_ROOT}/lib/aec-static.lib"
    "${SD_DEPS_ROOT}/lib/zs.lib"
    "${SD_DEPS_ROOT}/lib/bz2.lib"
    "${SD_DEPS_ROOT}/lib/lz4.lib"
    "${SD_DEPS_ROOT}/lib/lzma.lib"
    "${SD_DEPS_ROOT}/lib/zstd.lib"
    "${SD_DEPS_ROOT}/lib/libcrypto.lib"
    "${SD_DEPS_ROOT}/lib/pugixml.lib"
    shlwapi.lib
    xmllite.lib
    crypt32.lib
    ws2_32.lib
)
target_compile_definitions(sd_translation_extractor PRIVATE
    UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
if(MSVC)
    target_compile_options(sd_translation_extractor PRIVATE
        /W4 /WX /utf-8 /permissive- /Zc:__cplusplus)
    set_property(TARGET sd_translation_extractor PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
