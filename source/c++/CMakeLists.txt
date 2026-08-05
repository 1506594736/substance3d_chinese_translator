cmake_minimum_required(VERSION 3.21)
project(sp_translation_delegate LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(sp_translation_delegate SHARED translation_ui_delegate.cpp)

# The repository ships the Painter-compatible Qt headers and import libraries,
# but intentionally omits host tools such as moc/uic/rcc. This library contains
# no Q_OBJECT classes, so those tools are unnecessary. Link the compact SDK
# directly when present; a complete external Qt installation remains supported.
set(BUNDLED_QT_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/qt-sdk/6.5.3/msvc2019_64")
if(EXISTS "${BUNDLED_QT_ROOT}/lib/Qt6Core.lib"
   AND EXISTS "${BUNDLED_QT_ROOT}/lib/Qt6Gui.lib"
   AND EXISTS "${BUNDLED_QT_ROOT}/lib/Qt6Widgets.lib")
    target_include_directories(sp_translation_delegate PRIVATE
        "${BUNDLED_QT_ROOT}/include"
        "${BUNDLED_QT_ROOT}/include/QtCore"
        "${BUNDLED_QT_ROOT}/include/QtGui"
        "${BUNDLED_QT_ROOT}/include/QtWidgets"
        "${BUNDLED_QT_ROOT}/mkspecs/win32-msvc"
    )
    target_link_libraries(sp_translation_delegate PRIVATE
        "${BUNDLED_QT_ROOT}/lib/Qt6Core.lib"
        "${BUNDLED_QT_ROOT}/lib/Qt6Gui.lib"
        "${BUNDLED_QT_ROOT}/lib/Qt6Widgets.lib"
    )
    target_compile_definitions(sp_translation_delegate PRIVATE
        QT_CORE_LIB QT_GUI_LIB QT_WIDGETS_LIB)
    if(MSVC)
        target_compile_options(sp_translation_delegate PRIVATE
            /W4 /WX /Zc:__cplusplus /permissive- /utf-8)
    endif()
else()
    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)
    target_link_libraries(sp_translation_delegate PRIVATE
        Qt6::Core Qt6::Gui Qt6::Widgets)
endif()
target_compile_definitions(sp_translation_delegate PRIVATE UNICODE _UNICODE)
set_target_properties(sp_translation_delegate PROPERTIES
    OUTPUT_NAME "sp_translation_delegate"
    PREFIX ""
)
