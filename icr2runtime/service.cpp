#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include "memory.h"
#include "service.h"

#include <algorithm>
#include <atomic>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <map>
#include <cstring>
#include <set>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

// Versioned pipe name keeps clients bound to the matching service protocol.
constexpr wchar_t kPipeName[] = LR"(\\.\pipe\ICR2Runtime_v13)";
constexpr int kWorkerCount = 8;
constexpr unsigned kRefreshSeconds = 30;
constexpr std::size_t kMaxRequestBytes = 8192;
constexpr std::size_t kMaxBulkBytes = 64 * 1024;

bool gWritesEnabled = false;
bool gCodeWritesEnabled = false;
std::atomic<bool> gStopping{false};
std::atomic<unsigned> gActiveClients{0};
std::atomic<ULONGLONG> gLastActivityMs{0};
unsigned gIdleTimeoutSeconds = 0;

void touchActivity() {
    gLastActivityMs.store(GetTickCount64(), std::memory_order_relaxed);
}


struct PatchRecord {
    std::uint32_t pid = 0;
    std::string version;
    std::uintptr_t base = 0;
    std::uintptr_t address = 0;
    bool code = false;
    std::uint64_t processCreationTime = 0;
    std::vector<std::uint8_t> original;
    std::vector<std::uint8_t> current;
    bool guestCode = false; // RESTORE must use this patch's original page policy
};
std::mutex gPatchMutex;
std::map<std::pair<std::uint32_t, std::uintptr_t>, PatchRecord> gPatches;

// Animation leases are distinct from one-time patches. All access is serialized
// by gPatchMutex, including updates from different pipe worker threads.
struct AnimationRecord {
    PatchRecord identity;
};
std::map<std::pair<std::uint32_t, std::uintptr_t>, AnimationRecord> gAnimations;


std::string hexBytes(const std::vector<std::uint8_t>& bytes) {
    static constexpr char digits[] = "0123456789ABCDEF";
    std::string out;
    for (auto b : bytes) { out += digits[b >> 4]; out += digits[b & 15]; }
    return out;
}


// Recognized game signatures and offsets are specific to supported builds.
// Validate them cheaply against cached process handles before every read.
constexpr std::uint8_t kDosSignature[] = {
    0x55,0x6e,0x61,0x62,0x6c,0x65,0x20,0x74,0x6f,0x20,0x66,0x69,0x6e,
    0x64,0x20,0x49,0x6e,0x64,0x79,0x43,0x61,0x72,0x2e,0x65,0x78,0x65
};
constexpr std::uint8_t kRenditionSignature[] = {
    0x52,0x4e,0x31,0x20,0x42,0x75,0x69,0x6c,0x64,0x20,0x23,0x36,0x31
};
constexpr std::uint8_t kWindySignature[] = {
    0x57,0x69,0x6e,0x64,0x79,0x54,0x69,0x6d,0x65,0x72,0x50,0x68,
    0x79,0x73,0x53,0x65,0x6d,0x61,0x70,0x68,0x6f,0x72,0x65,0x00
};

std::uint64_t processCreationTime(std::uint32_t pid) {
    const HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!h) return 0;
    FILETIME created{}, exited{}, kernel{}, user{};
    const BOOL ok = GetProcessTimes(h, &created, &exited, &kernel, &user);
    CloseHandle(h);
    if (!ok) return 0;
    return (static_cast<std::uint64_t>(created.dwHighDateTime) << 32) |
           created.dwLowDateTime;
}

struct CachedGame {
    explicit CachedGame(GameConnection g)
        : info(std::move(g)), created(processCreationTime(info.processId)), memory(info) {}
    GameConnection info;
    std::uint64_t created = 0;
    GameMemory memory; // keeps the same read-only process handle open
};

bool signatureMatches(const CachedGame& game) {
    const std::uint8_t* expected = nullptr;
    std::size_t length = 0;
    std::uintptr_t offset = 0;
    if (game.info.version == "DOS102") {
        expected = kDosSignature;
        length = sizeof(kDosSignature);
        offset = 0xA4120;
    } else if (game.info.version == "REND32A") {
        expected = kRenditionSignature;
        length = sizeof(kRenditionSignature);
        offset = 0xB08D9;
    } else if (game.info.version == "WINDY101") {
        expected = kWindySignature;
        length = sizeof(kWindySignature);
        offset = 0x4F5A7C;
    } else {
        return false;
    }
    if (!game.memory.isOpen()) return false;
    std::array<std::uint8_t, 32> current{};
    if (length > current.size()) return false;
    if (!game.memory.readBytes(offset, current.data(), length)) return false;
    return std::equal(expected, expected + length, current.begin());
}

// Scan once on startup and once every 30 seconds, not on every READ.
// Snapshot copies are cheap and retain handles even while a refresh occurs.
class GameRegistry {
public:
    void refresh() {
        std::lock_guard<std::mutex> scanLock(refreshMutex_);
        const auto detected = detectGames();  // relatively expensive full scan
        std::vector<std::shared_ptr<CachedGame>> next;
        next.reserve(detected.size());
        for (const auto& game : detected) {
            std::shared_ptr<CachedGame> item;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                for (const auto& existing : games_) {
                    if (existing->info.processId == game.processId &&
                        existing->info.version == game.version &&
                        existing->info.addressTranslationBase == game.addressTranslationBase &&
                        existing->info.signatureAddress == game.signatureAddress &&
                        existing->created != 0 &&
                        existing->created == processCreationTime(game.processId)) {
                        item = existing;
                        break;
                    }
                }
            }
            if (!item) item = std::make_shared<CachedGame>(game);
            if (item->created != 0 && signatureMatches(*item)) next.push_back(std::move(item));
        }
        std::lock_guard<std::mutex> lock(mutex_);
        games_ = std::move(next);
        // Refreshed games may have disappeared or changed. Discard only their
        // old patch records; never restore bytes to an unrecognized process.
        std::lock_guard<std::mutex> patches(gPatchMutex);
        for (auto it = gPatches.begin(); it != gPatches.end(); ) {
            const auto& p = it->second;
            const bool current = std::any_of(games_.begin(), games_.end(),
                [&](const auto& g) {
                    return g->info.processId == p.pid &&
                        g->info.version == p.version &&
                        g->info.addressTranslationBase == p.base &&
                        g->created == p.processCreationTime;
                });
            if (!current) it = gPatches.erase(it);
            else ++it;
        }
        // Abandon leases on process exit/restart. Never restore to a new process.
        for (auto it = gAnimations.begin(); it != gAnimations.end();) {
            const auto& p = it->second.identity;
            const bool current = std::any_of(games_.begin(), games_.end(),
                [&](const auto& g) {
                    return g->info.processId == p.pid &&
                        g->info.version == p.version &&
                        g->info.addressTranslationBase == p.base &&
                        g->created == p.processCreationTime;
                });
            if (!current) it = gAnimations.erase(it);
            else ++it;
        }

    }

    std::vector<std::shared_ptr<CachedGame>> list() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return games_;
    }

    std::shared_ptr<CachedGame> get(std::uint32_t pid) const {
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& game : games_) {
            if (game->info.processId == pid) return game;
        }
        return {};
    }

private:
    mutable std::mutex mutex_;
    std::mutex refreshMutex_;
    std::vector<std::shared_ptr<CachedGame>> games_;
};

std::string safeTitle(const std::string& s) {
    std::string output;
    for (char c : s) {
        if (c == '\t' || c == '\n' || c == '\r') output += ' ';
        else output += c;
    }
    return output;
}

bool parseNumber(const std::string& raw, int base, std::uint64_t& result) {
    std::string s = raw;
    if (base == 16 && s.size() > 2 && s[0] == '0' &&
        (s[1] == 'x' || s[1] == 'X')) s.erase(0, 2);
    if (s.empty()) return false;
    const auto [end, error] = std::from_chars(s.data(), s.data() + s.size(), result, base);
    return error == std::errc{} && end == s.data() + s.size();
}

template <typename T>
std::string readTyped(const GameMemory& memory, std::uintptr_t address) {
    T value{};
    if (!memory.read(address, value)) return "ERR\tMEMORY_READ_FAILED\n";
    std::ostringstream output;
    output << "OK\t";
    if constexpr (std::is_same_v<T, std::uint8_t> || std::is_same_v<T, std::int8_t>) {
        output << static_cast<int>(value);
    } else if constexpr (std::is_floating_point_v<T>) {
        output << std::setprecision(std::numeric_limits<T>::max_digits10) << value;
    } else {
        output << value;
    }
    output << '\n';
    return output.str();
}

std::string readTypedByName(const GameMemory& memory,
                            std::uintptr_t address, const std::string& type) {
    if (type == "u8") return readTyped<std::uint8_t>(memory, address);
    if (type == "i8") return readTyped<std::int8_t>(memory, address);
    if (type == "u16") return readTyped<std::uint16_t>(memory, address);
    if (type == "i16") return readTyped<std::int16_t>(memory, address);
    if (type == "u32") return readTyped<std::uint32_t>(memory, address);
    if (type == "i32") return readTyped<std::int32_t>(memory, address);
    if (type == "u64") return readTyped<std::uint64_t>(memory, address);
    if (type == "i64") return readTyped<std::int64_t>(memory, address);
    if (type == "f32") return readTyped<float>(memory, address);
    if (type == "f64") return readTyped<double>(memory, address);
    return "ERR\tUNSUPPORTED_TYPE\n";
}

// Text-encoded bulk result is simple to inspect and works with Python's
// standard library.  It sends 2 ASCII hex characters per memory byte.
std::string readBulk(const GameMemory& memory, std::uintptr_t address,
                     std::size_t length) {
    if (length == 0 || length > kMaxBulkBytes) return "ERR\tINVALID_BULK_SIZE\n";
    std::vector<std::uint8_t> data(length);
    if (!memory.readBytes(address, data.data(), data.size()))
        return "ERR\tMEMORY_READ_FAILED\n";
    static constexpr char digits[] = "0123456789ABCDEF";
    std::string response;
    response.reserve(4 + length * 2 + 1);
    response += "OK\t";
    for (const auto byte : data) {
        response += digits[byte >> 4];
        response += digits[byte & 15];
    }
    response += '\n';
    return response;
}


// Strict hex byte parsing for compare-and-swap DATA patches.
bool decodeHex(const std::string& text, std::vector<std::uint8_t>& bytes,
               std::size_t maxBytes = 8) {
    if (text.empty() || text.size() > maxBytes * 2 || text.size() % 2) return false;
    auto digit = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    for (std::size_t i = 0; i < text.size(); i += 2) {
        int a = digit(text[i]), b = digit(text[i + 1]);
        if (a < 0 || b < 0) return false;
        bytes.push_back(static_cast<std::uint8_t>((a << 4) | b));
    }
    return true;
}

// File offset -> Ghidra address. Unsupported mappings explicitly fail.
// WINDY is PE32: translate raw file position using the actual section headers
// already loaded in the process, rather than assuming a fixed delta.
bool mapFileOffset(const CachedGame& game, std::uintptr_t fileOffset,
                   std::uintptr_t& ghidra) {
    if (game.info.version == "DOS102") {
        // Verified table in DOS102: Ford fuel at file 0xF9CD8 -> game 0xA8884.
        // Limit to the known contiguous Ford/Mercedes/Honda/chassis table.
        if (fileOffset < 0xF9CD8 || fileOffset >= 0xF9E00) return false;
        const auto candidate = static_cast<std::uintptr_t>(0xA8884) + (fileOffset - 0xF9CD8);
        // Safety check against a known immutable value in the same table.
        std::uint16_t fuel = 0;
        if (!game.memory.read(0xA8884, fuel) || (fuel != 6290 && fuel != 6291)) return false;
        ghidra = candidate;
        return true;
    }
    if (game.info.version == "REND32A") {
        // Verified Ford table: file F35D4 -> guest/Ghidra BB7B4.
        // This is intentionally restricted to a small table region; not a
        // claim about the DOS32A file's other segments.
        if (fileOffset < 0xF35D4 || fileOffset >= 0xF3700) return false;
        std::uint16_t fuel = 0;
        if (!game.memory.read(0xBB7B4, fuel) || (fuel != 6290 && fuel != 6291)) return false;
        ghidra = static_cast<std::uintptr_t>(0xBB7B4) + (fileOffset - 0xF35D4);
        return true;
    }
    if (game.info.version != "WINDY101" || !game.info.hostModuleBase) return false;
    // The WINDY main PE is based at hostModuleBase (normally 0x400000).
    // Read DOS header and NT header offsets via the existing Ghidra API.
    const std::uintptr_t module = game.info.hostModuleBase;
    const std::uintptr_t translate = game.info.addressTranslationBase;
    if (module < translate) return false;
    const std::uintptr_t dos = module - translate;
    std::uint16_t mz = 0;
    std::uint32_t ntRel = 0;
    if (!game.memory.read(dos, mz) || mz != 0x5A4D ||
        !game.memory.read(dos + 0x3C, ntRel) || ntRel > 0x1000) return false;
    std::uint32_t pe = 0;
    if (!game.memory.read(dos + ntRel, pe) || pe != 0x00004550) return false;
    std::uint16_t sections = 0, optSize = 0;
    if (!game.memory.read(dos + ntRel + 6, sections) || sections > 32 ||
        !game.memory.read(dos + ntRel + 20, optSize)) return false;
    const auto table = dos + ntRel + 24 + optSize;
    for (unsigned i = 0; i < sections; ++i) {
        const auto sh = table + i * 40;
        std::uint32_t virtualSize = 0, va = 0, rawSize = 0, rawStart = 0;
        if (!game.memory.read(sh + 8, virtualSize) || !game.memory.read(sh + 12, va) ||
            !game.memory.read(sh + 16, rawSize) || !game.memory.read(sh + 20, rawStart)) return false;
        if (fileOffset >= rawStart && fileOffset - rawStart < rawSize &&
            fileOffset - rawStart < virtualSize) {
            const auto host = module + va + fileOffset - rawStart;
            if (host < translate) return false;
            ghidra = host - translate;
            return true;
        }
    }
    return false;
}

bool gameMatchesPatch(const CachedGame& game, const PatchRecord& patch) {
    return game.info.processId == patch.pid &&
           game.info.version == patch.version &&
           game.info.addressTranslationBase == patch.base &&
           game.created == patch.processCreationTime &&
           game.created == processCreationTime(game.info.processId) && signatureMatches(game);
}


// SCAN requests target one bounded translated game-memory span. Bad pages are
// skipped in 64 KiB chunks, with overlap for matches crossing chunk edges.
std::string scanPattern(const GameMemory& memory, std::uintptr_t start,
                        std::size_t length, const std::vector<std::uint8_t>& pattern,
                        std::size_t limit) {
    if (pattern.empty() || length < pattern.size() || length > 16 * 1024 * 1024 ||
        limit < 1 || limit > 256 || start > UINTPTR_MAX - length)
        return "ERR\tINVALID_SCAN_RANGE\n";
    constexpr std::size_t chunk = 64 * 1024;
    std::vector<std::uintptr_t> hits;
    std::vector<std::uint8_t> buf;
    std::size_t examined = 0;
    // Advance in disjoint 64K positions, requesting overlap from each chunk.
    while (examined < length && hits.size() < limit) {
        const auto primary = std::min(chunk, length - examined);
        const auto extra = std::min(pattern.size() - 1, length - examined - primary);
        buf.resize(primary + extra);
        const auto at = start + examined;
        if (memory.readBytes(at, buf.data(), buf.size())) {
            auto it = buf.begin();
            while (it != buf.end()) {
                it = std::search(it, buf.end(), pattern.begin(), pattern.end());
                if (it == buf.end()) break;
                auto index = static_cast<std::size_t>(it - buf.begin());
                if (index < primary) hits.push_back(at + index);
                if (hits.size() >= limit) break;
                ++it;
            }
        }
        examined += primary;
    }
    std::ostringstream out;
    out << "OK\t" << hits.size() << '\n';
    for (auto addr : hits) out << "HIT\t" << std::hex << std::uppercase << addr << '\n';
    return out.str();
}

bool overlapsExisting(std::uint32_t pid, std::uintptr_t address, std::size_t len) {
    for (const auto& [key, p] : gPatches) {
        if (p.pid != pid) continue;
        if (address <= p.address ? p.address - address < len
                                 : address - p.address < p.current.size()) return true;
    }
    for (const auto& [key, animation] : gAnimations) {
        const auto& p = animation.identity;
        if (p.pid != pid) continue;
        if (address <= p.address ? p.address - address < len
                                 : address - p.address < p.current.size()) return true;
    }
    return false;
}

std::string serveRequest(GameRegistry& registry, const std::string& line) {
    std::istringstream input(line);
    std::string command;
    if (!(input >> command)) return "ERR\tEMPTY_REQUEST\n";
    if (command == "CAPS") {
        std::string caps = "OK\tREAD,BULK,MAP,PATCHES,RESTORE,SCAN,SESSION,PATCH24_READINESS,LIFECYCLE_IDLE";
        if (gWritesEnabled) caps += ",PATCH_DATA,PATCHBATCH,PATCH24,ANIM_BEGIN,ANIM_UPDATE,ANIM_END,ANIM_LIST";
        if (gCodeWritesEnabled) caps += ",PATCH_CODE,PATCH_GUEST_CODE";
        return caps + "\n";
    }
    if (command == "ANIM_LIST") {
        std::string extra;
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        std::lock_guard<std::mutex> lock(gPatchMutex);
        std::ostringstream out;
        out << "OK\t" << gAnimations.size() << '\n';
        for (const auto& [key, lease] : gAnimations) {
            const auto& p = lease.identity;
            out << "ANIM\t" << p.pid << '\t' << std::hex << std::uppercase
                << p.address << std::dec << '\n';
        }
        return out.str();
    }
    if (command == "ANIM_BEGIN" || command == "ANIM_UPDATE" || command == "ANIM_END") {
        if (!gWritesEnabled) return "ERR\tWRITES_DISABLED\n";
        std::string pidText, addrText, bytesText, extra;
        const bool ending = command == "ANIM_END";
        if (!(input >> pidText >> addrText) ||
            (!ending && !(input >> bytesText)) || (input >> extra))
            return "ERR\tBAD_REQUEST\n";
        std::uint64_t pid = 0, address = 0;
        if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
            !parseNumber(addrText, 16, address) || address > UINTPTR_MAX ||
            address > UINTPTR_MAX - 24) return "ERR\tBAD_ADDRESS_OR_PID\n";
        std::vector<std::uint8_t> bytes;
        if (!ending && (!decodeHex(bytesText, bytes, 24) || bytes.size() != 24))
            return "ERR\tINVALID_RECORD_BYTES\n";
        const auto game = registry.get(static_cast<std::uint32_t>(pid));
        if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";
        const auto addr = static_cast<std::uintptr_t>(address);
        const auto key = std::make_pair(static_cast<std::uint32_t>(pid), addr);
        std::lock_guard<std::mutex> lock(gPatchMutex);
        auto it = gAnimations.find(key);
        if (command == "ANIM_BEGIN") {
            if (it != gAnimations.end() || overlapsExisting(static_cast<std::uint32_t>(pid), addr, 24))
                return "ERR\tRECORD_ALREADY_OWNED_OR_OVERLAPS\n";
            // Caller supplies the expected original 24 bytes. Registration does
            // not write; it verifies the exact pre-animation snapshot.
            std::vector<std::uint8_t> observed(24);
            if (!game->memory.readBytes(addr, observed.data(), 24) || observed != bytes)
                return "ERR\tEXPECTED_BYTES_MISMATCH\n";
            PatchRecord p{static_cast<std::uint32_t>(pid), game->info.version,
                game->info.addressTranslationBase, addr, false, game->created,
                observed, observed};
            gAnimations.emplace(key, AnimationRecord{std::move(p)});
            return "OK\tREGISTERED\n";
        }
        if (it == gAnimations.end()) return "ERR\tRECORD_NOT_REGISTERED\n";
        PatchRecord& p = it->second.identity;
        if (!gameMatchesPatch(*game, p)) return "ERR\tGAME_CHANGED\n";
        if (ending) {
            if (!game->memory.patchDataBytes(addr, p.current, p.original))
                return "ERR\tRESTORE_FAILED_OR_CHANGED\n";
            gAnimations.erase(it);
            return "OK\tRESTORED\n";
        }
        if (!game->memory.patchDataBytes(addr, p.current, bytes))
            return "ERR\tUPDATE_FAILED_OR_CHANGED\n";
        p.current = std::move(bytes);
        return "OK\tUPDATED\n";
    }
    if (command == "MAP") {
        std::string pidText, fileText, extra;
        if (!(input >> pidText >> fileText) || (input >> extra)) return "ERR\tBAD_REQUEST\n";
        std::uint64_t pid = 0, off = 0;
        if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
            !parseNumber(fileText, 16, off) || off > UINTPTR_MAX) return "ERR\tBAD_REQUEST\n";
        const auto game = registry.get(static_cast<std::uint32_t>(pid));
        if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";
        std::uintptr_t mapped = 0;
        if (!mapFileOffset(*game, static_cast<std::uintptr_t>(off), mapped))
            return "ERR\tUNVERIFIED_FILE_MAPPING\n";
        std::ostringstream out;
        out << "OK\t" << std::uppercase << std::hex << mapped << "\n";
        return out.str();
    }
    if (command == "SCAN") {
        std::string pidText, startText, lengthText, hexText, limitText, extra;
        if (!(input >> pidText >> startText >> lengthText >> hexText >> limitText) ||
            (input >> extra)) return "ERR\tBAD_REQUEST\n";
        std::uint64_t pid = 0, start = 0, length = 0, limit = 0;
        std::vector<std::uint8_t> pattern;
        if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
            !parseNumber(startText, 16, start) || start > UINTPTR_MAX ||
            !parseNumber(lengthText, 10, length) || length > 16 * 1024 * 1024 ||
            !parseNumber(limitText, 10, limit) || limit > 256 ||
            !decodeHex(hexText, pattern, 32)) return "ERR\tBAD_REQUEST\n";
        const auto game = registry.get(static_cast<std::uint32_t>(pid));
        if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";
        return scanPattern(game->memory, static_cast<std::uintptr_t>(start),
                           static_cast<std::size_t>(length), pattern,
                           static_cast<std::size_t>(limit));
    }
    if (command == "PATCHBATCH") {
        if (!gWritesEnabled) return "ERR\tWRITES_DISABLED\n";
        std::string pidText, countText, extra;
        if (!(input >> pidText >> countText)) return "ERR\tBAD_REQUEST\n";
        std::uint64_t pid = 0, count = 0;
        if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
            !parseNumber(countText, 10, count) || count < 1 || count > 32)
            return "ERR\tBAD_REQUEST\n";
        struct Part {std::uintptr_t address; std::vector<std::uint8_t> before, after;};
        std::vector<Part> parts;
        for (unsigned i = 0; i < count; ++i) {
            std::string field;
            if (!(input >> field)) return "ERR\tBAD_REQUEST\n";
            auto a = field.find(':');
            auto b = field.find(':', a == std::string::npos ? a : a + 1);
            if (a == std::string::npos || b == std::string::npos) return "ERR\tBAD_REQUEST\n";
            std::uint64_t address = 0;
            Part p{};
            if (!parseNumber(field.substr(0, a), 16, address) || address > UINTPTR_MAX ||
                !decodeHex(field.substr(a+1, b-a-1), p.before) ||
                !decodeHex(field.substr(b+1), p.after) ||
                p.before.size() != p.after.size()) return "ERR\tBAD_REQUEST\n";
            p.address = static_cast<std::uintptr_t>(address);
            parts.push_back(std::move(p));
        }
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        const auto game = registry.get(static_cast<std::uint32_t>(pid));
        if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";
        std::lock_guard<std::mutex> lock(gPatchMutex);
        for (unsigned i = 0; i < parts.size(); ++i) {
            const auto& p = parts[i];
            if (p.address > UINTPTR_MAX - p.before.size() ||
                overlapsExisting(static_cast<std::uint32_t>(pid), p.address, p.before.size()))
                return "ERR\tPATCH_CONFLICT\n";
            for (unsigned j = 0; j < i; ++j) {
                const auto& prev = parts[j];
                if (p.address <= prev.address ? prev.address - p.address < p.before.size()
                                             : p.address - prev.address < prev.before.size())
                    return "ERR\tPATCH_CONFLICT\n";
            }
            std::vector<std::uint8_t> observed(p.before.size());
            if (!game->memory.readBytes(p.address, observed.data(), observed.size()) ||
                observed != p.before) return "ERR\tEXPECTED_BYTES_MISMATCH\n";
        }
        unsigned committed = 0;
        for (; committed < parts.size(); ++committed) {
            const auto& p = parts[committed];
            if (!game->memory.patchDataBytes(p.address, p.before, p.after)) break;
            gPatches[{static_cast<std::uint32_t>(pid), p.address}] = PatchRecord{
                static_cast<std::uint32_t>(pid), game->info.version,
                game->info.addressTranslationBase, p.address, false, game->created, p.before, p.after};
        }
        if (committed != parts.size()) {
            bool rollbackOk = true;
            for (unsigned j = committed; j > 0; --j) {
                const auto& p = parts[j-1];
                if (game->memory.patchDataBytes(p.address, p.after, p.before))
                    gPatches.erase({static_cast<std::uint32_t>(pid), p.address});
                else rollbackOk = false;
            }
            return rollbackOk ? "ERR\tBATCH_FAILED_ROLLED_BACK\n"
                              : "ERR\tBATCH_FAILED_PARTIAL_ROLLBACK\n";
        }
        for (const auto& p : parts) {
            std::vector<std::uint8_t> observed(p.after.size());
            if (!game->memory.readBytes(p.address, observed.data(), observed.size()) ||
                observed != p.after) return "ERR\tBATCH_COMMITTED_VERIFY_FAILED_RESTORE_REQUIRED\n";
        }
        return "OK\tBATCH_PATCHED\n";
    }
    if (command == "PATCHES") {
        std::lock_guard<std::mutex> lock(gPatchMutex);
        std::ostringstream out;
        out << "OK\t" << gPatches.size() << "\n";
        for (const auto& [key, patch] : gPatches)
            out << "PATCH\t" << patch.pid << '\t' << std::hex << std::uppercase
                << patch.address << std::dec << '\t'
                << (patch.guestCode ? "GUESTCODE" : (patch.code ? "CODE" : "DATA"))
                << '\t' << hexBytes(patch.original) << '\t' << hexBytes(patch.current) << '\n';
        return out.str();
    }
    if (command == "PATCH" || command == "PATCHCODE" || command == "PATCHGUESTCODE" ||
        command == "PATCH24" || command == "RESTORE") {
        const bool isRestore = command == "RESTORE";
        const bool guestCode = command == "PATCHGUESTCODE";
        const bool code = command == "PATCHCODE" || guestCode;
        const bool record24 = command == "PATCH24";
        if (!isRestore && ((code && !gCodeWritesEnabled) || (!code && !gWritesEnabled)))
            return "ERR\tWRITES_DISABLED\n";
        std::string pidText, addressText, beforeText, afterText, extra;
        if (isRestore) {
            if (!(input >> pidText >> addressText) || (input >> extra)) return "ERR\tBAD_REQUEST\n";
        } else if (!(input >> pidText >> addressText >> beforeText >> afterText) || (input >> extra))
            return "ERR\tBAD_REQUEST\n";
        std::uint64_t pid = 0, address = 0;
        if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
            !parseNumber(addressText, 16, address) || address > UINTPTR_MAX)
            return "ERR\tBAD_ADDRESS_OR_PID\n";
        const auto game = registry.get(static_cast<std::uint32_t>(pid));
        if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";
        const auto key = std::make_pair(static_cast<std::uint32_t>(pid),
                                        static_cast<std::uintptr_t>(address));
        if (guestCode && game->info.version != "DOS102" &&
            game->info.version != "REND32A")
            return "ERR\tGUEST_CODE_REQUIRES_DOS_GAME\n";
        std::lock_guard<std::mutex> lock(gPatchMutex);
        auto it = gPatches.find(key);
        if (isRestore) {
            if (it == gPatches.end()) return "ERR\tPATCH_NOT_TRACKED\n";
            const auto patch = it->second;
            if (!gameMatchesPatch(*game, patch)) return "ERR\tGAME_CHANGED\n";
            const bool ok = patch.guestCode
                ? game->memory.patchGuestCodeBytes(patch.address, patch.current, patch.original)
                : patch.code
                ? game->memory.patchCodeBytes(patch.address, patch.current, patch.original)
                : game->memory.patchDataBytes(patch.address, patch.current, patch.original);
            if (!ok) return "ERR\tRESTORE_FAILED_OR_CHANGED\n";
            gPatches.erase(it);
            return "OK\tRESTORED\n";
        }
        std::vector<std::uint8_t> before, after;
        if (!decodeHex(beforeText, before, record24 ? 24 : 8) ||
            !decodeHex(afterText, after, record24 ? 24 : 8) ||
            before.size() != after.size() ||
            (record24 && before.size() != 24)) return "ERR\tINVALID_PATCH_BYTES\n";
        // Do not allow overlapping patches. One owner for a byte range.
        for (const auto& [existingKey, patch] : gPatches) {
            if (patch.pid != pid) continue;
            const auto a = static_cast<std::uintptr_t>(address);
            if (a <= patch.address ? patch.address - a < after.size() :
                a - patch.address < patch.current.size())
                return "ERR\tPATCH_CONFLICT\n";
        }
        if (overlapsExisting(static_cast<std::uint32_t>(pid),
                             static_cast<std::uintptr_t>(address), after.size()))
            return "ERR\tPATCH_CONFLICT\n";
        const bool ok = guestCode
            ? game->memory.patchGuestCodeBytes(static_cast<std::uintptr_t>(address), before, after)
            : code
            ? game->memory.patchCodeBytes(static_cast<std::uintptr_t>(address), before, after)
            : game->memory.patchDataBytes(static_cast<std::uintptr_t>(address), before, after);
        if (!ok) return "ERR\tPATCH_REJECTED_OR_FAILED\n";
        gPatches[key] = PatchRecord{static_cast<std::uint32_t>(pid), game->info.version,
            game->info.addressTranslationBase, static_cast<std::uintptr_t>(address),
            code, game->created, std::move(before), std::move(after), guestCode};
        return "OK\tPATCHED\n";
    }
    if (command == "PATCH24_READINESS") {
        return "OK\t24_BYTE_DATA_PATCH,EXPECTED_BYTES,TRACKED_RESTORE\n";
    }
    if (command == "STATUS") {
        std::string extra;
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        std::lock_guard<std::mutex> lock(gPatchMutex);
        std::ostringstream out;
        out << "OK\t0.13\tIDLE_TIMEOUT=" << gIdleTimeoutSeconds
            << "\tACTIVE_CLIENTS=" << gActiveClients.load()
            << "\tTRACKED_PATCHES=" << gPatches.size()
            << "\tACTIVE_ANIMATIONS=" << gAnimations.size() << '\n';
        return out.str();
    }
    if (command == "PING") {
        std::string extra;
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        return "OK\tPONG\n";
    }
    if (command == "REFRESH") {
        std::string extra;
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        registry.refresh();
        return "OK\tREFRESHED\n";
    }
    if (command == "LIST") {
        std::string extra;
        if (input >> extra) return "ERR\tBAD_REQUEST\n";
        const auto games = registry.list();
        std::ostringstream out;
        out << "OK\t" << games.size() << '\n';
        for (const auto& game : games) {
            const auto& g = game->info;
            out << "GAME\t" << g.processId << '\t' << g.version << '\t'
                << std::hex << std::uppercase << g.addressTranslationBase << '\t'
                << g.hostModuleBase << std::dec << '\t' << safeTitle(g.windowTitle) << '\n';
        }
        return out.str();
    }
    if (command != "READ" && command != "BULK") return "ERR\tUNKNOWN_COMMAND\n";

    std::string pidText, addressText, argument, extra;
    if (!(input >> pidText >> addressText >> argument) || (input >> extra))
        return "ERR\tBAD_REQUEST\n";
    std::uint64_t pid = 0, address = 0;
    if (!parseNumber(pidText, 10, pid) || pid == 0 || pid > UINT32_MAX ||
        !parseNumber(addressText, 16, address) || address > UINTPTR_MAX)
        return "ERR\tBAD_ADDRESS_OR_PID\n";

    const auto game = registry.get(static_cast<std::uint32_t>(pid));
    if (!game || game->created == 0 ||
            game->created != processCreationTime(game->info.processId) ||
            !signatureMatches(*game)) return "ERR\tGAME_NOT_FOUND_OR_CHANGED\n";

    if (command == "READ")
        return readTypedByName(game->memory, static_cast<std::uintptr_t>(address), argument);

    std::uint64_t length = 0;
    if (!parseNumber(argument, 10, length) || length == 0 || length > kMaxBulkBytes)
        return "ERR\tINVALID_BULK_SIZE\n";
    return readBulk(game->memory, static_cast<std::uintptr_t>(address),
                    static_cast<std::size_t>(length));
}

// Ordinary clients use one request per connection; multiple workers allow
// multiple Python clients to connect simultaneously.
bool readRequest(HANDLE pipe, std::string& request) {
    request.clear();
    char c = 0;
    DWORD read = 0;
    while (request.size() < kMaxRequestBytes) {
        if (!ReadFile(pipe, &c, 1, &read, nullptr) || read != 1) return false;
        if (c == '\n') {
            if (!request.empty() && request.back() == '\r') request.pop_back();
            return true;
        }
        request += c;
    }
    return false;
}

void sendResponse(HANDLE pipe, const std::string& response) {
    std::size_t pos = 0;
    while (pos < response.size()) {
        const auto size = static_cast<DWORD>(
            std::min<std::size_t>(response.size() - pos, 64 * 1024));
        DWORD sent = 0;
        if (!WriteFile(pipe, response.data() + pos, size, &sent, nullptr) || sent == 0)
            return;
        pos += sent;
    }
    // Wait until the reader consumes the response before closing its pipe.
    FlushFileBuffers(pipe);
}

void serveClients(GameRegistry& registry, int workerNumber) {
    while (!gStopping.load()) {
        const HANDLE pipe = CreateNamedPipeW(
            kPipeName,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES,
            64 * 1024, 4 * 1024, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            std::cerr << "Pipe worker " << workerNumber
                      << " failed to create pipe: " << GetLastError() << '\n';
            return;
        }
        const BOOL connected = ConnectNamedPipe(pipe, nullptr);
        if (connected || GetLastError() == ERROR_PIPE_CONNECTED) {
            gActiveClients.fetch_add(1);
            touchActivity();
            std::string request;
            if (readRequest(pipe, request)) {
                if (request == "SESSION") {
                    auto framed = [&](const std::string& result) -> bool {
                        std::ostringstream header;
                        header << std::hex << std::uppercase << std::setw(8)
                               << std::setfill('0') << result.size() << '\n';
                        const auto frame = header.str() + result;
                        DWORD done = 0;
                        return WriteFile(pipe, frame.data(), static_cast<DWORD>(frame.size()),
                                         &done, nullptr) && done == frame.size();
                    };
                    if (framed("OK\tSESSION\n")) {
                        while (readRequest(pipe, request)) {
                            touchActivity();
                            if (request == "QUIT") { framed("OK\tBYE\n"); break; }
                            if (!framed(serveRequest(registry, request))) break;
                        }
                    }
                } else {
                    sendResponse(pipe, serveRequest(registry, request));
                }
            } else {
                sendResponse(pipe, "ERR\tREQUEST_TOO_LONG_OR_CLOSED\n");
            }
            DisconnectNamedPipe(pipe);
            gActiveClients.fetch_sub(1);
            touchActivity();
        }
        CloseHandle(pipe);
    }
}

// Wake synchronous ConnectNamedPipe workers so they can notice gStopping
// and exit. Only called when there are no application clients connected.
void wakeWorkers() {
    for (int i = 0; i < kWorkerCount * 4; ++i) {
        const HANDLE pipe = CreateFileW(kPipeName, GENERIC_READ | GENERIC_WRITE,
                                        0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            const DWORD error = GetLastError();
            if (error == ERROR_FILE_NOT_FOUND) break; // all workers have exited
            if (error == ERROR_PIPE_BUSY) WaitNamedPipeW(kPipeName, 100);
            continue;
        }
        constexpr char request[] = "PING\n";
        DWORD sent = 0, received = 0;
        WriteFile(pipe, request, sizeof(request) - 1, &sent, nullptr);
        char reply[64]{};
        ReadFile(pipe, reply, sizeof(reply), &received, nullptr);
        CloseHandle(pipe);
    }
}

bool hasPendingWrites() {
    std::lock_guard<std::mutex> lock(gPatchMutex);
    return !gPatches.empty() || !gAnimations.empty();
}

} // namespace

void runReadOnlyService(bool enableWrites, bool enableCodeWrites,
                        unsigned idleTimeoutSeconds) {
    gWritesEnabled = enableWrites;
    gCodeWritesEnabled = enableCodeWrites;
    gIdleTimeoutSeconds = idleTimeoutSeconds;
    gStopping.store(false);
    gActiveClients.store(0);
    touchActivity();

    std::cout << "ICR2Runtime v0.13 - shared memory service\n";
    std::cout << "Pipe: \\\\.\\pipe\\ICR2Runtime_v13\n";
    std::cout << "Cached process handles, BULK/SCAN/batch, up to " << kWorkerCount
              << " concurrent pipe requests.\n";
    std::cout << "Automatic game rescan every " << kRefreshSeconds << " seconds.\n";
    std::cout << "Writes: " << (gWritesEnabled ? "ENABLED (writable DATA pages only)" : "DISABLED") << "\n";
    std::cout << "Code writes: " << (gCodeWritesEnabled ? "ENABLED (native executable and DOSBox guest-code pages)" : "DISABLED") << "\n";
    if (gIdleTimeoutSeconds)
        std::cout << "Idle shutdown: " << gIdleTimeoutSeconds << " seconds with no connected clients"
                     " or pending patches/animations.\n";
    else
        std::cout << "Idle shutdown: disabled (persistent service).\n";

    GameRegistry registry;
    registry.refresh();
    std::cout << "Initially recognized games: " << registry.list().size() << '\n';

    std::thread refresher([&registry]() {
        while (!gStopping.load()) {
            for (unsigned i = 0; i < kRefreshSeconds && !gStopping.load(); ++i)
                std::this_thread::sleep_for(std::chrono::seconds(1));
            if (!gStopping.load()) registry.refresh();
        }
    });

    std::vector<std::thread> workers;
    workers.reserve(kWorkerCount);
    for (int i = 0; i < kWorkerCount; ++i)
        workers.emplace_back(serveClients, std::ref(registry), i + 1);

    // One-shot clients reset the idle clock on disconnect. Persistent sessions
    // count as active until they close, so dashboards/animators keep the service
    // alive. Pending writes additionally inhibit auto-exit to avoid abandoning
    // un-restored changes.
    while (!gStopping.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        if (gIdleTimeoutSeconds == 0 || gActiveClients.load() != 0 ||
            hasPendingWrites()) continue;
        const auto now = GetTickCount64();
        const auto last = gLastActivityMs.load(std::memory_order_relaxed);
        if (now >= last &&
            now - last >= static_cast<ULONGLONG>(gIdleTimeoutSeconds) * 1000) {
            // An incoming connection can race this final check; clients will
            // retry startup if they see the service closing.
            if (gActiveClients.load() == 0 && !hasPendingWrites())
                gStopping.store(true);
        }
    }
    wakeWorkers();
    for (auto& worker : workers) worker.join();
    refresher.join();
}
