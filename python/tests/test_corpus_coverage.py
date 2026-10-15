"""Coverage rule of the conformance corpus.

Every canonical kind in ``registry.json`` must appear in the ``kinds`` list of
at least one positive archive (``conformance/corpus/*.expected.json``), so a
consumer that passes the corpus has been shown every kind the format defines.
The kinds are read from the registry at test time: adding a kind to the
registry fails this test until an archive exercises it.
"""

import glob
import json
import os
import zipfile

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
REGISTRY = os.path.join(ROOT, "registry.json")
CONFORMANCE = os.path.join(ROOT, "conformance")
CORPUS = os.path.join(CONFORMANCE, "corpus")

MAX_ARCHIVE_BYTES = 100 * 1024


def _require_corpus():
    if not (os.path.isfile(REGISTRY) and os.path.isdir(CORPUS)):
        pytest.skip("registry.json or conformance/corpus not present "
                    "(standalone checkout)")


def _expectations():
    out = []
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.expected.json"))):
        with open(path, encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def _canonical_kinds():
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)["canonical_kinds"]


def test_every_canonical_kind_has_a_positive_archive():
    _require_corpus()
    covered = {}
    for exp in _expectations():
        for kind in exp["kinds"]:
            covered.setdefault(kind, []).append(exp["archive"])
    missing = [k for k in _canonical_kinds() if k not in covered]
    assert not missing, (
        f"canonical kinds with no positive archive in conformance/corpus: "
        f"{missing}. Add an archive to conformance/generate_corpus.py "
        f"(see conformance/README.md, 'Coverage').")


def test_expected_kinds_match_the_archives():
    """The coverage claim rests on the ``kinds`` lists, so check them against
    the manifests rather than trusting them."""
    _require_corpus()
    for exp in _expectations():
        with zipfile.ZipFile(os.path.join(CORPUS, exp["archive"])) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        kinds = sorted({s["kind"] for s in manifest["sections"]})
        assert exp["kinds"] == kinds, exp["archive"]


def test_corpus_kinds_are_canonical_or_vendor():
    """A typo in a ``kinds`` list must not count as coverage of anything."""
    _require_corpus()
    canonical = set(_canonical_kinds())
    for exp in _expectations():
        for kind in exp["kinds"]:
            assert kind in canonical or kind.startswith("x_"), \
                (exp["archive"], kind)


@pytest.mark.parametrize("directory", ["corpus", "negative", "legacy"])
def test_every_archive_has_an_expectation_and_stays_small(directory):
    """An archive without an ``expected.json`` is never run, and one without
    its archive fails the runner; every committed archive stays under
    100 KiB."""
    path = os.path.join(CONFORMANCE, directory)
    if not os.path.isdir(path):
        pytest.skip(f"conformance/{directory} not present")
    archives = {f[:-4] for f in os.listdir(path) if f.endswith(".qvf")}
    expected = {f[:-len(".expected.json")] for f in os.listdir(path)
                if f.endswith(".expected.json")}
    assert archives == expected, (directory, archives ^ expected)
    for name in sorted(archives):
        size = os.path.getsize(os.path.join(path, name + ".qvf"))
        assert size < MAX_ARCHIVE_BYTES, (directory, name, size)
