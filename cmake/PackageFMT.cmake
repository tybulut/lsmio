# Google-Log
find_package(fmt 10.2.1 QUIET)
if (NOT fmt_FOUND)
  include(FetchContent)
  set(FETCHCONTENT_QUIET FALSE)

  FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG        10.2.1
    GIT_PROGRESS   TRUE
  )

  FetchContent_MakeAvailable(fmt)
endif()

