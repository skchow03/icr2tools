#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <type_traits>
#include <vector>

struct GameConnection {
    std::string version;
    std::string windowTitle;
    unsigned long processId = 0;
    // Windows address where the host EXE (WINDY or DOSBox) is loaded.
    std::uintptr_t hostModuleBase = 0;

    // Add this to an ICR2 Ghidra address to obtain a host memory address.
    // DOS: location of guest image in DOSBox; WINDY: usually zero.
    std::uintptr_t addressTranslationBase = 0;

    std::uintptr_t signatureAddress = 0;
};

// Find supported ICR2 builds within running WINDY/DOSBox instances.
std::vector<GameConnection> detectGames();

// Retains a read-only handle. Patch calls use a separate, short-lived write handle.
class GameMemory {
public:
    explicit GameMemory(const GameConnection& game);
    ~GameMemory();

    GameMemory(const GameMemory&) = delete;
    GameMemory& operator=(const GameMemory&) = delete;

    bool isOpen() const { return process_ != nullptr; }

    // Addresses are the Ghidra addresses used by the version's memory map.
    // Host address = addressTranslationBase + ghidraAddress.
    // This is not generally relative to the Windows module base.
    bool readBytes(std::uintptr_t offset, void* destination, std::size_t byteCount) const;

    // Compare-and-swap an existing writable DATA value. Does not change page protections.
    // An exact expected-byte match is mandatory, avoiding blind patches.
    bool patchDataBytes(std::uintptr_t offset,
                        const std::vector<std::uint8_t>& expected,
                        const std::vector<std::uint8_t>& replacement) const;

    // Guarded code modification: compare bytes, temporarily enable writing,
    // restore original page protection and flush instruction cache.
    bool patchCodeBytes(std::uintptr_t offset,
                        const std::vector<std::uint8_t>& expected,
                        const std::vector<std::uint8_t>& replacement) const;

    // DOSBox guest instructions are stored in writable host data pages.
    // The service must validate DOS102/REND32A and the process instance first.
    bool patchGuestCodeBytes(std::uintptr_t offset,
                             const std::vector<std::uint8_t>& expected,
                             const std::vector<std::uint8_t>& replacement) const {
        // DOSBox stores guest instructions as host writable DATA. Reuse the
        // already tested exact-compare, write, and read-back validation path.
        return !expected.empty() && expected.size() <= 8 &&
               patchDataBytes(offset, expected, replacement);
    }

    template <typename T>
    bool read(std::uintptr_t offset, T& value) const {
        static_assert(std::is_trivially_copyable_v<T>,
                      "GameMemory::read<T> requires a simple data type");
        return readBytes(offset, &value, sizeof(T));
    }

private:
    unsigned long pid_ = 0;
    HANDLE process_ = nullptr;
    std::uintptr_t addressTranslationBase_ = 0;
};
