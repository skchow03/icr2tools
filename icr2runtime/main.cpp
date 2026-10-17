#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "service.h"
#include <charconv>
#include <iostream>
#include <string_view>

int main(int argc, char** argv) {
    bool data = false, code = false;
    unsigned idleTimeout = 0; // Manual service launches remain persistent.
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        if (arg == "--enable-data-writes") data = true;
        else if (arg == "--enable-code-writes") code = true;
        else if (arg == "--idle-timeout" && i + 1 < argc) {
            const std::string_view value(argv[++i]);
            unsigned parsed = 0;
            const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
            if (result.ec != std::errc{} || result.ptr != value.data() + value.size() ||
                parsed > 3600) {
                std::cerr << "--idle-timeout requires seconds in the range 0..3600\n";
                return 2;
            }
            idleTimeout = parsed;
        } else {
            std::cerr << "Usage: icr2runtime.exe [--enable-data-writes] "
                         "[--enable-code-writes] [--idle-timeout 0..3600]\n";
            return 2;
        }
    }

    // Serializes concurrent application launchers without requiring any
    // shared Python state or racing on pipe creation.
    const HANDLE singleton = CreateMutexW(nullptr, FALSE, L"Local\\ICR2Runtime_v12_Service");
    if (!singleton) {
        std::cerr << "Unable to create runtime singleton mutex: " << GetLastError() << '\n';
        return 1;
    }
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        std::cout << "ICR2Runtime v0.12 is already starting or running.\n";
        CloseHandle(singleton);
        return 0;
    }

    runReadOnlyService(data, code, idleTimeout);
    CloseHandle(singleton);
    return 0;
}
