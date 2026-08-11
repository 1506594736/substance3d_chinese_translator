cmake_minimum_required(VERSION 3.21)
project(sp_tools_delegate LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Painter 10.1+ / Qt6。qt-sdk 为两个插件共用的构建工具链，
# 位于 source/qt-sdk（不属于任何插件的插件源码）。
set(QT6_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../public/sdks/qt/6.5.3/msvc2019_64")
if(NOT EXISTS "${QT6_ROOT}/lib/Qt6Widgets.lib")
    message(FATAL_ERROR "Bundled Qt6 SDK is missing")
endif()

add_library(sp_tools_delegate SHARED sp_tools_delegate.cpp)
target_include_directories(sp_tools_delegate PRIVATE
    "${QT6_ROOT}/include"
    "${QT6_ROOT}/include/QtCore"
    "${QT6_ROOT}/include/QtGui"
    "${QT6_ROOT}/include/QtWidgets"
    "${QT6_ROOT}/mkspecs/win32-msvc"
)
target_link_libraries(sp_tools_delegate PRIVATE
    "${QT6_ROOT}/lib/Qt6Core.lib"
    "${QT6_ROOT}/lib/Qt6Gui.lib"
    "${QT6_ROOT}/lib/Qt6Widgets.lib"
)
target_compile_definitions(sp_tools_delegate PRIVATE
    QT_CORE_LIB QT_GUI_LIB QT_WIDGETS_LIB UNICODE _UNICODE)
if(MSVC)
    target_compile_options(sp_tools_delegate PRIVATE
        /W4 /Zc:__cplusplus /permissive- /utf-8)
endif()
set_target_properties(sp_tools_delegate PROPERTIES
    OUTPUT_NAME "sp_layer_tools_delegate_qt6"
    PREFIX ""
)
