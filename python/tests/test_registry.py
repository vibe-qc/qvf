"""Drift guard: registry.json's canonical_kinds must match the schema exactly.

The governance registry (`registry.json`) advertises the canonical section
kinds. It must stay in lock-step with the schema's `Section` branches — the
schema is the single source of truth — so a tool trusting the registry can never
be told about a kind the schema doesn't define, or miss one it does.
"""

import json
import os

import pytest

HERE = os.path.dirname(__file__)
_REGISTRY = os.path.normpath(os.path.join(HERE, "..", "..", "registry.json"))
_SCHEMA = os.path.normpath(os.path.join(HERE, "..", "..", "spec",
                                        "qvf_manifest.schema.json"))


def _schema_canonical_kinds(schema: dict) -> set:
    defs = schema["$defs"]
    kinds = set()
    for branch in defs["Section"]["oneOf"]:
        ref = branch["$ref"].split("/")[-1]
        kc = defs.get(ref, {}).get("properties", {}).get("kind", {})
        if "const" in kc:  # vendor branch has a pattern, not a const — skipped
            kinds.add(kc["const"])
    return kinds


def test_registry_canonical_kinds_match_schema():
    if not (os.path.exists(_REGISTRY) and os.path.exists(_SCHEMA)):
        pytest.skip("registry/schema not present (standalone checkout)")
    registry = json.load(open(_REGISTRY, encoding="utf-8"))
    schema = json.load(open(_SCHEMA, encoding="utf-8"))
    reg_kinds = set(registry["canonical_kinds"])
    schema_kinds = _schema_canonical_kinds(schema)
    missing = schema_kinds - reg_kinds
    extra = reg_kinds - schema_kinds
    assert not missing and not extra, (
        f"registry.json out of sync with schema — missing: {sorted(missing)}, "
        f"extra: {sorted(extra)}"
    )


def test_registry_vendor_namespaces_well_formed():
    if not os.path.exists(_REGISTRY):
        pytest.skip("registry not present")
    registry = json.load(open(_REGISTRY, encoding="utf-8"))
    for ns in registry.get("vendor_namespaces", []):
        assert ns["namespace"].startswith("x_"), ns
        assert "owner" in ns and "purpose" in ns, ns
