cmake_minimum_required(VERSION 3.20)
project(ICR2Runtime LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(icr2runtime main.cpp memory.cpp service.cpp)
target_link_libraries(icr2runtime PRIVATE Psapi)
