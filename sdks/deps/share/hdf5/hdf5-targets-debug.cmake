#----------------------------------------------------------------
# Generated CMake target import file for configuration "Debug".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "hdf5::hdf5-static" for configuration "Debug"
set_property(TARGET hdf5::hdf5-static APPEND PROPERTY IMPORTED_CONFIGURATIONS DEBUG)
set_target_properties(hdf5::hdf5-static PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_DEBUG "C"
  IMPORTED_LOCATION_DEBUG "${_IMPORT_PREFIX}/debug/lib/libhdf5.lib"
  )

list(APPEND _cmake_import_check_targets hdf5::hdf5-static )
list(APPEND _cmake_import_check_files_for_hdf5::hdf5-static "${_IMPORT_PREFIX}/debug/lib/libhdf5.lib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
