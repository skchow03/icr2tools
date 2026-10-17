#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#include "memory.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace {

struct Signature {
    const char* version;
    std::vector<std::uint8_t> bytes;
    std::uintptr_t imageOffset;
};

// From icr2_core/icr2_memory.py in skchow03/icr2tools.
const std::array<Signature, 3> signatures = {{
    {"DOS102", {0x55,0x6e,0x61,0x62,0x6c,0x65,0x20,0x74,0x6f,0x20,0x66,0x69,0x6e,0x64,0x20,0x49,0x6e,0x64,0x79,0x43,0x61,0x72,0x2e,0x65,0x78,0x65}, 0xA4120},
    {"REND32A", {0x52,0x4e,0x31,0x20,0x42,0x75,0x69,0x6c,0x64,0x20,0x23,0x36,0x31}, 0xB08D9},
    {"WINDY101", {0x57,0x69,0x6e,0x64,0x79,0x54,0x69,0x6d,0x65,0x72,0x50,0x68,0x79,0x73,0x53,0x65,0x6d,0x61,0x70,0x68,0x6f,0x72,0x65,0x00}, 0x4F5A7C},
}};

struct WindowTarget { DWORD pid; std::string title; };

// Main module of the Windows HOST process: DOSBox.exe or WINDY.EXE.
// May return 0 if enumeration is unavailable; game signature detection
// remains independent of this informational value.
std::uintptr_t getHostModuleBase(HANDLE process) {
    HMODULE firstModule = nullptr;
    DWORD needed = 0;
    if (!EnumProcessModules(process, &firstModule, sizeof(firstModule), &needed))
        return 0;
    if (needed < sizeof(firstModule) || !firstModule)
        return 0;
    return reinterpret_cast<std::uintptr_t>(firstModule);
}

std::string lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {return static_cast<char>(std::tolower(c));});
    return text;
}

BOOL CALLBACK collectWindows(HWND hwnd, LPARAM param) {
    if (!IsWindowVisible(hwnd)) return TRUE;
    const int size = GetWindowTextLengthA(hwnd);
    if (size <= 0) return TRUE;
    std::string title(static_cast<std::size_t>(size) + 1, '\0');
    int copied = GetWindowTextA(hwnd, title.data(), size + 1);
    if (copied <= 0) return TRUE;
    title.resize(static_cast<std::size_t>(copied));
    const std::string t = lower(title);
    if (t.find("dosbox") == std::string::npos && t.find("cart racing") == std::string::npos && t.find("indycar racing") == std::string::npos) return TRUE;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid) static_cast<std::vector<WindowTarget>*>(reinterpret_cast<void*>(param))->push_back({pid,title});
    return TRUE;
}

bool readable(const DWORD protect) {
    if (protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    const DWORD p = protect & 0xff;
    return p == PAGE_READONLY || p == PAGE_READWRITE || p == PAGE_WRITECOPY ||
           p == PAGE_EXECUTE_READ || p == PAGE_EXECUTE_READWRITE || p == PAGE_EXECUTE_WRITECOPY;
}

// Read in chunks with overlap so signatures crossing chunk boundaries are found.
std::uintptr_t scanForSignature(HANDLE process, const Signature& sig) {
    SYSTEM_INFO sys{};
    GetNativeSystemInfo(&sys);
    auto pos = reinterpret_cast<std::uintptr_t>(sys.lpMinimumApplicationAddress);
    const auto end = reinterpret_cast<std::uintptr_t>(sys.lpMaximumApplicationAddress);
    constexpr SIZE_T chunkSize = 64 * 1024;
    std::vector<std::uint8_t> buffer(chunkSize);
    std::vector<std::uint8_t> overlap;

    while (pos < end) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQueryEx(process, reinterpret_cast<LPCVOID>(pos), &mbi, sizeof(mbi))) break;
        auto start = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress);
        if (mbi.RegionSize == 0 || start > end || mbi.RegionSize > end - start) break;
        const auto regionEnd = start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && readable(mbi.Protect)) {
            overlap.clear();
            for (std::uintptr_t addr = start; addr < regionEnd;) {
                const auto size = static_cast<SIZE_T>(std::min<std::uintptr_t>(chunkSize, regionEnd - addr));
                SIZE_T got = 0;
                if (ReadProcessMemory(process, reinterpret_cast<LPCVOID>(addr), buffer.data(), size, &got) && got) {
                    std::vector<std::uint8_t> data;
                    data.reserve(overlap.size() + got);
                    data.insert(data.end(), overlap.begin(), overlap.end());
                    data.insert(data.end(), buffer.begin(), buffer.begin() + got);
                    auto it = std::search(data.begin(), data.end(), sig.bytes.begin(), sig.bytes.end());
                    if (it != data.end()) {
                        return (addr - overlap.size()) + static_cast<std::uintptr_t>(it - data.begin());
                    }
                    const auto keep = std::min(data.size(), sig.bytes.size() - 1);
                    overlap.assign(data.end() - keep, data.end());
                } else {
                    overlap.clear();
                }
                addr += size;
            }
        }
        pos = regionEnd;
    }
    return 0;
}

} // namespace

std::vector<GameConnection> detectGames() {
    std::vector<WindowTarget> targets;
    EnumWindows(collectWindows, reinterpret_cast<LPARAM>(&targets));
    std::vector<GameConnection> found;
    std::vector<DWORD> processed;

    for (const auto& target : targets) {
        if (std::find(processed.begin(), processed.end(), target.pid) != processed.end()) continue;
        processed.push_back(target.pid);
        HANDLE process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, target.pid);
        if (!process) continue;
        for (const auto& sig : signatures) {
            // WINDY signature is meaningful only for a WINDY-like window; likewise for DOSBox.
            const auto t = lower(target.title);
            const bool dosbox = t.find("dosbox") != std::string::npos;
            if (dosbox == (std::string(sig.version) == "WINDY101")) continue;
            auto hit = scanForSignature(process, sig);
            if (!hit || hit < sig.imageOffset) continue;
            found.push_back({
                sig.version, target.title, target.pid,
                getHostModuleBase(process),
                hit - sig.imageOffset,
                hit
            });
            break;
        }
        CloseHandle(process);
    }
    return found;
}

GameMemory::GameMemory(const GameConnection& game)
    : pid_(game.processId), addressTranslationBase_(game.addressTranslationBase) {
    process_ = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                           FALSE, game.processId);
}

GameMemory::~GameMemory() {
    if (process_) CloseHandle(process_);
}

bool GameMemory::readBytes(std::uintptr_t offset, void* destination,
                           std::size_t byteCount) const {
    if (!process_ || !destination || !byteCount) return false;
    // Protect against unsigned overflow when calculating the host address.
    if (offset > UINTPTR_MAX - addressTranslationBase_) return false;
    const std::uintptr_t address = addressTranslationBase_ + offset;
    if (byteCount > UINTPTR_MAX - address) return false;

    SIZE_T bytesRead = 0;
    const BOOL success = ReadProcessMemory(
        process_, reinterpret_cast<LPCVOID>(address),
        destination, byteCount, &bytesRead);
    return success != FALSE && bytesRead == byteCount;
}

// This intentionally refuses read-only or executable pages; v0.6 is DATA-only.
// It also refuses a write if the value differs from the caller's expected bytes.
bool GameMemory::patchDataBytes(std::uintptr_t offset,
        const std::vector<std::uint8_t>& expected,
        const std::vector<std::uint8_t>& replacement) const {
    if (!process_ || expected.empty() || expected.size() != replacement.size() ||
        expected.size() > 24 || offset > UINTPTR_MAX - addressTranslationBase_)
        return false;
    const std::uintptr_t address = addressTranslationBase_ + offset;
    if (expected.size() > UINTPTR_MAX - address) return false;
    HANDLE writer = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ |
                                PROCESS_VM_WRITE | PROCESS_VM_OPERATION,
                                FALSE, pid_);
    if (!writer) return false;
    bool ok = false;
    do {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQueryEx(writer, reinterpret_cast<LPCVOID>(address), &mbi, sizeof(mbi))) break;
        const auto protection = mbi.Protect & 0xff;
        if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)) ||
            !(protection == PAGE_READWRITE || protection == PAGE_WRITECOPY)) break;
        const auto base = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress);
        if (address < base || address - base > mbi.RegionSize ||
            expected.size() > mbi.RegionSize - (address - base)) break;
        std::vector<std::uint8_t> current(expected.size());
        SIZE_T count = 0;
        if (!ReadProcessMemory(writer, reinterpret_cast<LPCVOID>(address),
                current.data(), current.size(), &count) || count != current.size()) break;
        if (current != expected) break;
        count = 0;
        if (!WriteProcessMemory(writer, reinterpret_cast<LPVOID>(address),
                replacement.data(), replacement.size(), &count) || count != replacement.size()) break;
        std::vector<std::uint8_t> observed(replacement.size());
        count = 0;
        ok = ReadProcessMemory(writer, reinterpret_cast<LPCVOID>(address),
                observed.data(), observed.size(), &count) &&
                count == observed.size() && observed == replacement;
    } while (false);
    CloseHandle(writer);
    return ok;
}


bool GameMemory::patchCodeBytes(std::uintptr_t offset,
        const std::vector<std::uint8_t>& expected,
        const std::vector<std::uint8_t>& replacement) const {
    if (!process_ || expected.empty() || expected.size() > 8 ||
        expected.size() != replacement.size() ||
        offset > UINTPTR_MAX - addressTranslationBase_) return false;
    const std::uintptr_t address = addressTranslationBase_ + offset;
    if (expected.size() > UINTPTR_MAX - address) return false;
    HANDLE writer = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ |
                                PROCESS_VM_WRITE | PROCESS_VM_OPERATION, FALSE, pid_);
    if (!writer) return false;
    bool success = false;
    do {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQueryEx(writer, reinterpret_cast<LPCVOID>(address), &mbi, sizeof(mbi))) break;
        const auto protection = mbi.Protect & 0xff;
        if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)) ||
            !(protection == PAGE_EXECUTE_READ || protection == PAGE_EXECUTE_READWRITE ||
              protection == PAGE_EXECUTE_WRITECOPY)) break;
        const auto base = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress);
        if (address < base || address - base > mbi.RegionSize ||
            expected.size() > mbi.RegionSize - (address - base)) break;
        std::vector<std::uint8_t> old(expected.size());
        SIZE_T n = 0;
        if (!ReadProcessMemory(writer, reinterpret_cast<LPCVOID>(address),
                old.data(), old.size(), &n) || n != old.size() || old != expected) break;
        DWORD previous = 0;
        if (!VirtualProtectEx(writer, reinterpret_cast<LPVOID>(address), expected.size(),
                              PAGE_EXECUTE_READWRITE, &previous)) break;
        n = 0;
        const bool wrote = WriteProcessMemory(writer, reinterpret_cast<LPVOID>(address),
                                             replacement.data(), replacement.size(), &n) &&
                           n == replacement.size();
        FlushInstructionCache(writer, reinterpret_cast<LPCVOID>(address), replacement.size());
        DWORD ignored = 0;
        const bool protectedAgain = VirtualProtectEx(writer, reinterpret_cast<LPVOID>(address),
                                                     expected.size(), previous, &ignored) != 0;
        std::vector<std::uint8_t> observed(replacement.size());
        n = 0;
        success = wrote && protectedAgain &&
                  ReadProcessMemory(writer, reinterpret_cast<LPCVOID>(address),
                                    observed.data(), observed.size(), &n) &&
                  n == observed.size() && observed == replacement;
    } while (false);
    CloseHandle(writer);
    return success;
}
