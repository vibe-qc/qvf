"""The typed manifest model (``qvf_model``): lossless round trips.

``Manifest.from_json(m).to_json()`` must reproduce every manifest exactly as a
JSON value: every corpus, negative and legacy manifest that parses, and
manifests mutated into every shape the model does not type. The C++ model
(``qvf/model.hpp``) is held to the same rule by ``qvf_reader_tests
--model-roundtrip`` (CTest ``qvf_model_roundtrip``).
"""

import copy
import glob
import json
import os
import random
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))

from qvf_model import Manifest, MemberSpec, Section, Source  # noqa: E402
from qvf_reader import QvfReader  # noqa: E402

CONF = os.path.join(ROOT, "conformance")


def _canonical(value):
    """JSON text that tells 1 from 1.0 and true from 1, keys sorted."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _manifests():
    out = []
    for path in sorted(glob.glob(os.path.join(CONF, "*", "*.qvf"))):
        try:
            with zipfile.ZipFile(path) as zf:
                infos = [i for i in zf.infolist() if i.filename == "manifest.json"]
                if not infos:
                    continue
                doc = json.loads(zf.read(infos[-1]))
        except Exception:  # noqa: BLE001 - archives that are not ZIP or not JSON
            continue
        if isinstance(doc, dict):
            out.append((os.path.relpath(path, CONF), doc))
    return out


def test_every_conformance_manifest_round_trips():
    manifests = _manifests()
    if not manifests:
        pytest.skip("conformance corpus not present (standalone checkout)")
    corpus = [name for name, _ in manifests if name.startswith("corpus")]
    assert len(corpus) == len(glob.glob(os.path.join(CONF, "corpus", "*.qvf")))
    for name, doc in manifests:
        model = Manifest.from_json(doc)
        back = model.to_json()
        assert _canonical(back) == _canonical(doc), name
        again = Manifest.from_json(back).to_json()
        assert json.dumps(again) == json.dumps(back), name   # idempotent, order included


def test_corpus_manifests_are_typed():
    """On a valid manifest every known field is typed and nothing is left over."""
    for name, doc in _manifests():
        if not name.startswith("corpus"):
            continue
        m = Manifest.from_json(doc)
        assert m.qvf_version == 1 and isinstance(m.source, Source), name
        assert m.sections is not None and not m.extra, (name, m.extra)
        for s in m.sections:
            assert s.id and s.kind and s.members is not None, name
            for role, spec in s.members.items():
                assert spec.path and spec.sha256 and spec.format in ("json", "binary",
                                                                     "opaque"), (name, role)
                assert not spec.extra, (name, role, spec.extra)
                assert (spec.format == "binary") == (spec.dtype is not None), (name, role)


def test_reader_exposes_the_model():
    path = os.path.join(CONF, "corpus", "structure_slab_2d.qvf")
    if not os.path.exists(path):
        pytest.skip("conformance corpus not present")
    with QvfReader(path) as r:
        m = r.typed_manifest
        assert isinstance(m, Manifest)
        assert m.to_json() == r.manifest
        s = m.sections[0]
        assert m.section(s.id) is s and s.member("structure").format == "json"


def test_wrongly_typed_fields_are_kept_verbatim():
    doc = {
        "qvf_version": 1.0, "schema_uri": 7, "byte_order": "big",
        "source": {"program": "p", "version": "1"},          # incomplete: kept as is
        "provenance": [1], "metadata": {"title": "x"}, "x_vendor": {"a": 1},
        "sections": [
            {"id": 3, "kind": "structure", "label": None, "critical": "yes",
             "structure_ref": "s", "operand_a": "a",
             "members": {"structure": {"path": "s.json", "format": "json", "sha256": "0",
                                       "size": -1, "shape": [1.5], "x": True}}},
            {"id": "b", "kind": "bonds", "members": {"bonds": "not an object"}},
            {"id": "c", "kind": "x_v.k", "members": {"m": {"format": "text", "dtype": 4}}},
        ],
    }
    m = Manifest.from_json(doc)
    assert m.qvf_version is None and m.extra["qvf_version"] == 1.0
    assert m.byte_order == "big" and m.source is None and m.extra["source"] == doc["source"]
    assert m.provenance is None and m.metadata == {"title": "x"}
    s0, s1, s2 = m.sections
    assert s0.id is None and s0.extra["id"] == 3 and s0.critical is None
    assert s0.extra["operand_a"] == "a" and s0.structure_ref == "s"
    spec = s0.member("structure")
    assert spec.size is None and spec.shape is None and spec.extra == {
        "size": -1, "shape": [1.5], "x": True}
    assert s1.members is None and s1.extra["members"] == {"bonds": "not an object"}
    assert s2.member("m").format is None and s2.member("m").extra == {"format": "text",
                                                                        "dtype": 4}
    assert _canonical(m.to_json()) == _canonical(doc)
    with pytest.raises(TypeError):
        Manifest.from_json([])
    with pytest.raises(TypeError):
        Section.from_json("x")
    with pytest.raises(TypeError):
        MemberSpec.from_json(None)


def test_formats():
    assert MemberSpec.from_json({"format": "binary", "dtype": "float64"}).format == "binary"
    assert MemberSpec.from_json({"format": "binary"}).format == "opaque"
    assert MemberSpec.from_json({"format": "json"}).format == "json"
    assert MemberSpec(path="p", format="opaque").to_json() == {"path": "p", "format": "binary"}


def test_mutated_manifests_round_trip():
    """Random damage anywhere in a corpus manifest never loses anything."""
    manifests = [doc for name, doc in _manifests() if name.startswith("corpus")]
    if not manifests:
        pytest.skip("conformance corpus not present")
    rnd = random.Random(7)
    values = [None, True, 0, 1.0, -2, "s", "", [], {}, [1, "a"], {"k": [None]}]

    def nodes(v, path=()):
        yield path, v
        if isinstance(v, dict):
            for k, x in v.items():
                yield from nodes(x, path + (k,))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                yield from nodes(x, path + (i,))

    for _ in range(400):
        doc = copy.deepcopy(rnd.choice(manifests))
        for _ in range(rnd.randint(1, 4)):
            path, _node = rnd.choice([p for p in nodes(doc) if p[0]])
            parent = doc
            for p in path[:-1]:
                parent = parent[p]
            if isinstance(parent, dict) and rnd.random() < 0.3:
                del parent[path[-1]]
            else:
                parent[path[-1]] = copy.deepcopy(rnd.choice(values))
        assert _canonical(Manifest.from_json(doc).to_json()) == _canonical(doc)
