cmake_minimum_required(VERSION 3.28)

project(vt-tunnel-config LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Vendored FTXUI (third_party/FTXUI): build only the screen/dom/component
# libraries — examples, tests and docs stay off, and nothing is fetched at
# configure or build time.
set(FTXUI_BUILD_EXAMPLES OFF)
set(FTXUI_BUILD_TESTS OFF)
set(FTXUI_BUILD_DOCS OFF)
add_subdirectory(third_party/FTXUI)

add_executable(vt-tunnel-config
  src/main.cpp
)
target_link_libraries(vt-tunnel-config
  PRIVATE ftxui::dom
          ftxui::screen
          ftxui::component
)
