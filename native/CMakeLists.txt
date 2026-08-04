cmake_minimum_required(VERSION 3.21)
project(sp_native_asset_delegate LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

add_library(sp_native_asset_delegate SHARED native_asset_delegate.cpp)
target_link_libraries(sp_native_asset_delegate PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
target_compile_definitions(sp_native_asset_delegate PRIVATE UNICODE _UNICODE)
set_target_properties(sp_native_asset_delegate PROPERTIES
    OUTPUT_NAME "sp_native_asset_delegate"
    PREFIX ""
)
