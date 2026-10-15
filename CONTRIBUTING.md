# Contributing to QVF

QVF uses the toolset's existing
[contribution and verification process](https://github.com/vibe-qc/vibe-qc/blob/main/CONTRIBUTING.md).
Keep patches focused, explain the expected behavior, and include relevant
tests and conformance results. QVF contributions are under this repository's
**Apache-2.0** license; see [LICENSE](LICENSE).

Keep real machine configuration, credentials, account names and private
data outside the source tree. Enable the staged-content privacy hook once
per clone:

```sh
git config --local core.hooksPath .githooks
python3 .githooks/test_privacy_hook.py -q
```

Use documented placeholders for paths and RFC 5737 address ranges for
examples. The hook checks staged text, and does not replace the filename,
binary, secret and full-publication scans required before publishing a
snapshot. Report security and privacy issues privately per [SECURITY.md](SECURITY.md).

### Continuous integration

Every push to `main` and every pull request runs
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) on GitHub. The in-house
[`.gitlab-ci.yml`](.gitlab-ci.yml) pipeline runs the same checks on Linux, so
change both files together. CI checks:

- **Python tests** on Python 3.9, 3.11 and 3.14, including the privacy hook
  self-test.
- **Conformance corpus** through the reference runner.
- **C++ build and tests** on Linux (gcc and clang), macOS (clang) and Windows
  (MSVC), with warnings as errors: `-Wall -Wextra -Werror`, or `/W4 /WX` on MSVC,
  then the C++ conformance runner over the positive, negative and legacy corpora.
- **Sanitizers**: the C++ tests (the conformance runner included) under
  AddressSanitizer and UndefinedBehaviorSanitizer (clang), then the C++ reader
  over every `conformance/corpus/*.qvf` archive. A sanitizer finding fails the
  job.
- **Single-header amalgamation**: `cpp/qvf_single.hpp` is generated and must
  match its sources.
- **Generated tables**: the kind, unit and finding-code tables and the
  compiled JSON Schema (C++, TypeScript, Python) are generated from the schema
  by `scripts/gen_kinds.py` and must match it.

Run the same checks locally from the repository root:

```sh
# Python tests (CI uses 3.9, 3.11 and 3.14)
python .githooks/test_privacy_hook.py -q
pip install -e "python/[validate]" pytest
python -m pytest python/tests -q

# Conformance corpus
python conformance/run_conformance.py

# C++ build and tests with warnings as errors. Pass the flags through CXXFLAGS,
# not -DCMAKE_CXX_FLAGS, so CMake keeps its MSVC defaults. On MSVC use
# /W4 /WX, and add --config Release / -C Release for Visual Studio generators.
CXXFLAGS="-Wall -Wextra -Werror" cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
# The C++ conformance runner (ctest runs it as qvf_conformance; this shows the report)
./build/run_conformance conformance/corpus --negative conformance/negative --legacy conformance/legacy

# C++ under AddressSanitizer + UndefinedBehaviorSanitizer, then the reader over
# the corpus (build/ is ignored by version control)
SAN="-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g"
CC=clang CXX=clang++ CFLAGS="$SAN" CXXFLAGS="$SAN" \
  cmake -S cpp -B build/san -DCMAKE_BUILD_TYPE=Debug
cmake --build build/san
ctest --test-dir build/san --output-on-failure
for f in conformance/corpus/*.qvf; do
  ./build/san/read_qvf "$f" || break
done

# Fuzzing the ZIP reader and the validator (clang; not run in CI yet). Where
# clang has no libFuzzer runtime, the target uses a built-in mutation driver.
CC=clang CXX=clang++ cmake -S cpp -B build/fuzz -DCMAKE_BUILD_TYPE=Debug -DQVF_FUZZ=ON
cmake --build build/fuzz --target zip_reader_fuzzer
mkdir -p build/fuzz/corpus   # libFuzzer adds new inputs to the first directory only
./build/fuzz/zip_reader_fuzzer -max_total_time=60 build/fuzz/corpus conformance/corpus conformance/negative

# Generated tables: check them, and regenerate after editing the schema,
# registry.json or spec Appendix B (then regenerate the single header too)
python scripts/gen_kinds.py --check
python scripts/gen_kinds.py

# Generated single header: check it, and regenerate after editing cpp/include or cpp/src
python scripts/amalgamate.py --check
python scripts/amalgamate.py
```

### Private operator configuration

Deployment configuration is maintained separately from the format source.
Private literal terms can be supplied to the contributor guard through
`VIBE_PRIVACY_TERMS_FILE` or clone-local `privacy.termsFile`. Use an absolute
path to a UTF-8 file outside every Git checkout and object database, one
literal per line. Matching is case-insensitive; an explicitly configured
missing, empty or in-repository file blocks the check, including symlinks
through a checkout. Never commit the private policy or resolved home paths.

Keep operator configuration and audit evidence in external private storage.
The toolset uses an absolute `VIBE_PRIVATE_ROOT`, defaulting to
`${XDG_STATE_HOME:-$HOME/.local/state}/vibe-private`; it must resolve outside
Git repositories. A terms file can live under `qvf/config/` in that root.
Set `VIBE_PRIVACY_TERMS_FILE` to its absolute path explicitly; QVF does not
create or discover private policy files automatically. Use owner-only
directories (0700) and files (0600), and keep credentials in your existing
secret store. Ordinary build outputs and caches are unaffected.
