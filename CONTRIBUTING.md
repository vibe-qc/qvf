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

Ordinary development pushes and merges use `[skip ci]` and the supported
`ci.skip` push option. Run only the focused source checks for a development
change. Full CI belongs to authorized release candidates, using
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) and
[`.gitlab-ci.yml`](.gitlab-ci.yml). Keep both definitions aligned. Candidate
CI checks:

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

For an authorized candidate, these are the equivalent checks from the
repository root. Run native commands under your native-build lock; keep
operational logs outside the source tree.

```sh
# Python tests (CI uses 3.9, 3.11 and 3.14)
python .githooks/test_privacy_hook.py -q
pip install -e "python/[numpy,validate]" pytest
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


### Release and adoption checklist

This checklist is for the release/updater owner. It does not add release CI,
publication or a second review as a gate on ordinary source changes.

1. **Freeze the intended source.** Check ownership and incoming commits before
   choosing a candidate. Keep the toolkit version consistent in `VERSION`,
   language packages, CMake, citation metadata, README/roadmap and changelog.
   Record public-contract decisions in `GOVERNANCE.md`; confirm compatibility,
   canonical units and the unchanged or explicitly authorized format version.
   Keep later Unreleased work outside the candidate.
2. **Check the source inventory.** Run the affected generators' `--check`
   modes (`gen_kinds.py`, `amalgamate.py`, `gen_fortran.py`). Build source
   archives with `scripts/make_archive.sh --output-dir` naming an external
   directory. Check that tar and ZIP contain exactly committed source bytes,
   including positive, negative and legacy corpus fixtures, license and notices.
   Preserve binary fixtures intentionally designed to be unreadable; reconcile
   their exact hashes with the approved publication review before exporting.
3. **Qualify the candidate.** Run the authorized candidate CI at the frozen
   commit: language/platform checks, shared finding codes, corpus parity,
   generated files and sanitizers. A failing job holds that candidate. Fix the
   cause, identify the resulting commit, and repeat only affected checks until
   a complete qualifying candidate result exists. Do not label pending or
   unverified scientific results as passing.
4. **Check installed consumption.** Build wheel/sdist and smoke-test the
   documented imports/CLI with declared extras. Verify CMake/pkg-config
   installation from outside the source checkout and exercise static/shared
   C/C++ clients. If the [local Conan recipe](packaging/conan/README.md) is
   included, run its `test_package` under the native-build lock and retain the
   recipe revision/profile. Claim Fortran support only for compiler/platform
   combinations actually checked; installed modules are compiler-specific.
5. **Release and publish through the approved path.** Only the authorized owner
   creates the immutable tag after acceptance. Inspect the actual publication
   receipt and anonymous destination readback, including source identity,
   inventory and provenance. Tag presence alone is not publication acceptance.
   Scanner policy, schema hosting, distribution naming and media-type
   registration remain maintainer decisions. A local Conan create is not a
   package-index upload; registry publication requires its own authorization.
6. **Adopt and record.** Each family consumer pins one release tag and vendors
   byte-identical contract files. Run the affected reader/writer or handoff
   check for that consumer, preserve original archives and report unsupported
   kinds explicitly. Save source/runtime/test identities and release evidence
   in the private operational record. Remove only owned temporary outputs
   after the evidence is durable; keep reusable caches and active jobs intact.
