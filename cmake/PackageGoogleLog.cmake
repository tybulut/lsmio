# Google-Log
find_package(glog 0.7 QUIET)
if (NOT glog_FOUND)
  include(FetchContent)

  FetchContent_Declare(
    glog
    GIT_REPOSITORY https://github.com/google/glog.git
    GIT_TAG        v0.7.1
    FIND_PACKAGE_ARGS  GLOBAL
  )

  FetchContent_MakeAvailable(glog)
endif()

