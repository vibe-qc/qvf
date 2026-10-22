#!/usr/bin/env python3
"""Round-trip all canonical kinds through the pure C examples; Python validates.

License: Apache-2.0.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import zipfile
from qvf.validate import validate_qvf


def check(writer: Path, reader: Path, corpus: Path, output: Path, registry: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    seen = set()
    count = 0
    for original in sorted(corpus.rglob("*.qvf")):
        target = output / f"case-{count}.qvf"
        subprocess.run([str(writer), str(original), str(target)], check=True)
        report = validate_qvf(str(target))
        if not report["ok"]:
            raise AssertionError(f"{original.name}: {report['findings']}")
        subprocess.run([str(reader), str(target)], check=True, stdout=subprocess.DEVNULL)
        with zipfile.ZipFile(original) as before, zipfile.ZipFile(target) as after:
            old = json.loads(before.read("manifest.json"))
            new = json.loads(after.read("manifest.json"))
            assert len(old["sections"]) == len(new["sections"])
            for a, b in zip(old["sections"], new["sections"]):
                seen.add(a["kind"])
                assert {k: v for k, v in a.items() if k != "members"} == {
                    k: v for k, v in b.items() if k != "members"}
                assert a["members"].keys() == b["members"].keys()
                for role, member in a["members"].items():
                    x = before.read(member["path"])
                    y = after.read(b["members"][role]["path"])
                    if member.get("format") == "json":
                        assert json.loads(x) == json.loads(y), (original.name, role)
                    else:
                        assert x == y, (original.name, role)
        count += 1
    expected = set(json.loads(registry.read_text())["canonical_kinds"])
    assert expected <= seen, f"canonical kinds not exercised: {sorted(expected-seen)}"
    print(json.dumps({"archives": count, "canonical_kinds": len(expected), "ok": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", type=Path, required=True)
    parser.add_argument("--reader", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path("conformance/corpus"))
    parser.add_argument("--registry", type=Path, default=Path("registry.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check(args.writer.resolve(), args.reader.resolve(), args.corpus, args.output, args.registry)
