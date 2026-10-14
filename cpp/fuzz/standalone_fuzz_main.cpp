// standalone_fuzz_main.cpp — a driver for LLVMFuzzerTestOneInput where the
// compiler ships no libFuzzer runtime (Apple clang, for one).
//
//   zip_reader_fuzzer [-max_total_time=SECONDS] [-runs=N] [-seed=S] [PATH ...]
//
// Replays every file under the PATHs (directories are walked), then mutates
// randomly chosen inputs until the time or run budget is spent: bit flips,
// "interesting" 8/16/32/64-bit values written at random offsets or next to
// ZIP signatures, truncation, insertion, duplication and splicing. There is
// no coverage feedback, so this is weaker than libFuzzer, but every input
// runs under the same sanitizers. The sequence is determined by -seed; on a
// sanitizer death the input is written to crash-<run>.bin for replay.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <string>
#include <vector>

#if defined(__has_include)
#if __has_include(<sanitizer/common_interface_defs.h>)
#include <sanitizer/common_interface_defs.h>
#define QVF_HAVE_DEATH_CALLBACK 1
#endif
#endif

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size);

namespace {

std::vector<uint8_t> g_current;
uint64_t g_run = 0;

void save_current() {
    const std::string name = "crash-" + std::to_string(g_run) + ".bin";
    if (FILE* f = std::fopen(name.c_str(), "wb")) {
        if (!g_current.empty()) std::fwrite(g_current.data(), 1, g_current.size(), f);
        std::fclose(f);
        std::fprintf(stderr, "standalone fuzzer: input written to %s\n", name.c_str());
    }
}

void run_one(const std::vector<uint8_t>& input) {
    g_current = input;
    ++g_run;
    LLVMFuzzerTestOneInput(input.data(), input.size());
}

void load(const std::filesystem::path& p, std::vector<std::vector<uint8_t>>& out) {
    namespace fs = std::filesystem;
    std::error_code ec;
    if (fs::is_directory(p, ec)) {
        for (const auto& e : fs::recursive_directory_iterator(p, ec))
            if (e.is_regular_file(ec)) load(e.path(), out);
        return;
    }
    std::ifstream fh(p, std::ios::binary);
    if (!fh) return;
    out.emplace_back((std::istreambuf_iterator<char>(fh)), std::istreambuf_iterator<char>());
}

void put_le(std::vector<uint8_t>& v, size_t at, uint64_t value, int width) {
    for (int i = 0; i < width && at + static_cast<size_t>(i) < v.size(); ++i)
        v[at + static_cast<size_t>(i)] = static_cast<uint8_t>(value >> (8 * i));
}

}  // namespace

int main(int argc, char** argv) {
    double max_time = 0;
    uint64_t max_runs = 0;
    uint64_t seed = 1;
    std::vector<std::vector<uint8_t>> pool;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a.rfind("-max_total_time=", 0) == 0) max_time = std::atof(a.c_str() + 16);
        else if (a.rfind("-runs=", 0) == 0) max_runs = std::strtoull(a.c_str() + 6, nullptr, 10);
        else if (a.rfind("-seed=", 0) == 0) seed = std::strtoull(a.c_str() + 6, nullptr, 10);
        else if (!a.empty() && a[0] == '-') std::fprintf(stderr, "ignoring option %s\n", a.c_str());
        else load(a, pool);
    }
#ifdef QVF_HAVE_DEATH_CALLBACK
    __sanitizer_set_death_callback(save_current);
#endif
    // The smallest valid ZIP (an empty end record) as a seed of last resort.
    std::vector<uint8_t> empty_zip(22, 0);
    put_le(empty_zip, 0, 0x06054b50u, 4);
    pool.push_back(empty_zip);

    for (const auto& input : pool) run_one(input);
    std::fprintf(stderr, "standalone fuzzer: replayed %zu inputs; seed %llu\n", pool.size(),
                 static_cast<unsigned long long>(seed));

    std::mt19937_64 rng(seed);
    auto pick = [&rng](uint64_t n) { return n ? rng() % n : 0; };
    static const uint32_t kSigs[] = {0x04034b50u, 0x02014b50u, 0x06054b50u, 0x06064b50u,
                                     0x07064b50u, 0x08074b50u};
    static const uint64_t kValues[] = {0, 1, 2, 0x7F, 0x80, 0xFF, 0xFFFF, 0x7FFFFFFF,
                                       0x80000000ull, 0xFFFFFFFFull, 0xFFFFFFFFFFFFFFFFull,
                                       0x100000000ull, 30, 46, 22, 56, 65535, 65536};
    const auto start = std::chrono::steady_clock::now();
    uint64_t mutated = 0;
    while (true) {
        const double elapsed =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        if (max_runs && mutated >= max_runs) break;
        if (!max_runs && elapsed >= (max_time > 0 ? max_time : 10)) break;
        if (max_runs && max_time > 0 && elapsed >= max_time) break;
        std::vector<uint8_t> v = pool[pick(pool.size())];
        const int n_mut = 1 + static_cast<int>(pick(8));
        for (int m = 0; m < n_mut; ++m) {
            const uint64_t kind = pick(9);
            if (v.empty() && kind != 5 && kind != 8) continue;
            const size_t at = static_cast<size_t>(pick(v.size()));
            switch (kind) {
                case 0: v[at] ^= static_cast<uint8_t>(1u << pick(8)); break;
                case 1: v[at] = static_cast<uint8_t>(rng()); break;
                case 2: {
                    const int width = 1 << pick(4);   // 1, 2, 4, 8
                    put_le(v, at, kValues[pick(sizeof kValues / sizeof kValues[0])], width);
                    break;
                }
                case 3: {   // a field next to a ZIP signature
                    const uint32_t sig = kSigs[pick(sizeof kSigs / sizeof kSigs[0])];
                    std::vector<size_t> hits;
                    for (size_t p = 0; p + 4 <= v.size(); ++p)
                        if (std::memcmp(&v[p], &sig, 4) == 0) hits.push_back(p);
                    if (hits.empty()) break;
                    const size_t base = hits[pick(hits.size())];
                    const int width = pick(2) ? 4 : (pick(2) ? 2 : 8);
                    put_le(v, base + 4 + static_cast<size_t>(pick(52)),
                           kValues[pick(sizeof kValues / sizeof kValues[0])], width);
                    break;
                }
                case 4: v.resize(at); break;
                case 5: {
                    const size_t n = static_cast<size_t>(pick(64)) + 1;
                    std::vector<uint8_t> junk(n);
                    for (auto& b : junk) b = static_cast<uint8_t>(rng());
                    v.insert(v.begin() + static_cast<std::ptrdiff_t>(v.empty() ? 0 : at),
                             junk.begin(), junk.end());
                    break;
                }
                case 6: {
                    const size_t len = static_cast<size_t>(pick(std::min<size_t>(v.size() - at, 256))) + 1;
                    std::vector<uint8_t> chunk(v.begin() + static_cast<std::ptrdiff_t>(at),
                                               v.begin() + static_cast<std::ptrdiff_t>(
                                                               std::min(v.size(), at + len)));
                    v.insert(v.begin() + static_cast<std::ptrdiff_t>(pick(v.size())),
                             chunk.begin(), chunk.end());
                    break;
                }
                case 7: {
                    const size_t len = static_cast<size_t>(pick(std::min<size_t>(v.size() - at, 64))) + 1;
                    v.erase(v.begin() + static_cast<std::ptrdiff_t>(at),
                            v.begin() + static_cast<std::ptrdiff_t>(std::min(v.size(), at + len)));
                    break;
                }
                case 8: {
                    const std::vector<uint8_t>& other = pool[pick(pool.size())];
                    if (other.empty()) break;
                    const size_t from = static_cast<size_t>(pick(other.size()));
                    v.resize(v.empty() ? 0 : at);
                    v.insert(v.end(), other.begin() + static_cast<std::ptrdiff_t>(from), other.end());
                    break;
                }
            }
        }
        run_one(v);
        ++mutated;
        if (mutated % 20000 == 0)
            std::fprintf(stderr, "standalone fuzzer: %llu mutated runs, %.0f s\n",
                         static_cast<unsigned long long>(mutated), elapsed);
    }
    const double total =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::fprintf(stderr, "standalone fuzzer: done, %llu mutated runs in %.1f s, no crash\n",
                 static_cast<unsigned long long>(mutated), total);
    return 0;
}
