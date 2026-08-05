cmake_minimum_required(VERSION 3.21)
project(sp_translation_delegates LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

function(add_painter_delegate target output_name qt_root qt_major)
    add_library(${target} SHARED translation_ui_delegate.cpp)
    target_include_directories(${target} PRIVATE
        "${qt_root}/include"
        "${qt_root}/include/QtCore"
        "${qt_root}/include/QtGui"
        "${qt_root}/include/QtWidgets"
        "${qt_root}/mkspecs/win32-msvc"
    )
    target_link_libraries(${target} PRIVATE
        "${qt_root}/lib/Qt${qt_major}Core.lib"
        "${qt_root}/lib/Qt${qt_major}Gui.lib"
        "${qt_root}/lib/Qt${qt_major}Widgets.lib"
    )
    target_compile_definitions(${target} PRIVATE
        QT_CORE_LIB QT_GUI_LIB QT_WIDGETS_LIB UNICODE _UNICODE)
    if(MSVC)
        target_compile_options(${target} PRIVATE
            /W4 /WX /Zc:__cplusplus /permissive- /utf-8)
    endif()
    set_target_properties(${target} PROPERTIES
        OUTPUT_NAME "${output_name}"
        PREFIX ""
    )
endfunction()

# Painter 10.1+ / Qt6. The Qt6 ABI remains compatible across the supported
# minor versions used by current Painter releases.
set(QT6_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../qt-sdk/6.5.3/msvc2019_64")
if(NOT EXISTS "${QT6_ROOT}/lib/Qt6Widgets.lib")
    message(FATAL_ERROR "Bundled Qt6 SDK is missing")
endif()
add_painter_delegate(
    sp_translation_delegate_qt6 sp_translation_delegate_qt6 "${QT6_ROOT}" 6)

# Painter 7.2-10.0 / Qt5.12.5. This target is deliberately a separate DLL;
# loading a Qt6-linked delegate into a Qt5 process is unsafe.
set(QT5_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../qt-sdk/5.12.5/msvc2017_64")
if(NOT EXISTS "${QT5_ROOT}/lib/Qt5Widgets.lib")
    message(FATAL_ERROR "Bundled Qt5.12.5 SDK is missing")
endif()
add_painter_delegate(
    sp_translation_delegate_qt5 sp_translation_delegate_qt5 "${QT5_ROOT}" 5)
