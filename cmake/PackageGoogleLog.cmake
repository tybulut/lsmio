# Google-Log
find_package(glog 0.7 QUIET)
if (NOT glog_FOUND)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  FetchContent_Declare(
    glog
    GIT_REPOSITORY https://github.com/google/glog.git
    GIT_TAG        v0.7.1
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(glog)
endif()

