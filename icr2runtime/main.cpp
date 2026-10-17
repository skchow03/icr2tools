#include "service.h"
#include <iostream>
#include <string_view>

int main(int argc, char** argv) {
    bool data = false, code = false;
    for (int i = 1; i < argc; ++i) {
        const std::string_view arg(argv[i]);
        if (arg == "--enable-data-writes") data = true;
        else if (arg == "--enable-code-writes") code = true;
        else {
            std::cerr << "Usage: icr2runtime.exe [--enable-data-writes] [--enable-code-writes]\n";
            return 2;
        }
    }
    runReadOnlyService(data, code);
    return 0;
}
