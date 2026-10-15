"""Hygiene guards for the prose inside ``spec/qvf_manifest.schema.json``.

The schema is public and is the single source of truth for the QVF contract, so
its ``description`` / ``$comment`` strings must be self-contained:

* they must not cite documents or implementation details that are not part of
  this repository (internal design notes, a particular producer's Python API,
  how one consumer happens to load the file);
* every ``QVF spec § n.n (<title>)`` citation must resolve to a heading that
  really exists in ``spec/qvf-format-spec.md``, with the number *and* the title
  matching, so a renumbered or retitled section is caught here rather than left
  to rot.

Descriptions are not contract: editing them never changes what validates. The
last test therefore only confirms that the schema is still a valid Draft 2020-12
schema that accepts every frozen corpus archive.
"""

import json
import re
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "spec" / "qvf_manifest.schema.json"
_SPEC = _ROOT / "spec" / "qvf-format-spec.md"
_CORPUS = _ROOT / "conformance" / "corpus"

# Tokens that must never appear anywhere in the schema text.
_FORBIDDEN = ("design_qvf_format", "vibeqc.", "symlink")

# `§ 5.1`, `§ 6`, `§ 7.4`: the section number, then an optional parenthesised
# title. The title group is optional only so a missing title is reported as such
# instead of the citation being silently skipped.
_CITATION = re.compile(r"§\s*(\d+(?:\.\d+)*)(?:\s*\(([^()]*)\))?")
_APPENDIX_REF = re.compile(r"Appendix\s+([A-Z](?:\.\d+)?)")

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")
_APPENDIX_HEADING = re.compile(r"^(Appendix [A-Z]|[A-Z]\.\d+)\b")


def _require(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not present (standalone checkout)")


def _schema_text() -> str:
    _require(_SCHEMA)
    return _SCHEMA.read_text(encoding="utf-8")


def _walk_strings(node, path=""):
    """Yield ``(json_path, text)`` for every description / $comment string."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("description", "$comment") and isinstance(v, str):
                yield f"{path}/{k}", v
            yield from _walk_strings(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}/{i}")


def _spec_headings():
    """Return ``(numbered, labels)`` parsed from the spec's markdown headings.

    ``numbered`` maps a section number such as ``"7.4"`` to its title with any
    backticks removed; ``labels`` holds appendix labels (``"Appendix A"``,
    ``"A.3"``). Lines inside fenced code blocks are not headings.
    """
    _require(_SPEC)
    numbered, labels = {}, set()
    in_fence = False
    for line in _SPEC.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if not m:
            continue
        text = m.group(1)
        n = _NUMBERED.match(text)
        if n:
            numbered[n.group(1)] = n.group(2).replace("`", "").strip()
            continue
        a = _APPENDIX_HEADING.match(text)
        if a:
            labels.add(a.group(1))
    return numbered, labels


def test_no_forbidden_tokens_in_schema():
    raw = _schema_text()
    # Also check the decoded form, so a \uXXXX escape cannot hide a token.
    decoded = json.dumps(json.loads(raw), ensure_ascii=False)
    for token in _FORBIDDEN:
        for label, text in (("raw", raw), ("decoded", decoded)):
            assert token.lower() not in text.lower(), (
                f"forbidden token {token!r} found in the schema ({label} text); "
                "descriptions must state the contract itself, not cite internal "
                "documents or implementation details"
            )


def test_section_citations_resolve_to_spec_headings():
    schema = json.loads(_schema_text())
    numbered, labels = _spec_headings()
    assert numbered, "no numbered headings parsed from the spec"

    problems, citations_seen = [], 0
    for path, text in _walk_strings(schema):
        if "§" in text and "QVF spec §" not in text:
            problems.append(f"{path}: cites § without the form 'QVF spec § n.n'")
        for m in _CITATION.finditer(text):
            citations_seen += 1
            number, title = m.group(1), m.group(2)
            if number not in numbered:
                problems.append(f"{path}: § {number} is not a heading in the spec")
            elif title is None:
                problems.append(
                    f"{path}: § {number} lacks the parenthesised title "
                    f"(expected '({numbered[number]})')"
                )
            elif title != numbered[number]:
                problems.append(
                    f"{path}: § {number} is titled {numbered[number]!r} in the "
                    f"spec, not {title!r}"
                )
        for m in _APPENDIX_REF.finditer(text):
            ref = m.group(1)
            label = ref if "." in ref else f"Appendix {ref}"
            if label not in labels:
                problems.append(f"{path}: Appendix {ref} is not a heading in the spec")

    assert citations_seen, "no '§ n.n' citations found; is the citation regex broken?"
    assert not problems, "stale or malformed spec citations:\n" + "\n".join(problems)


def test_schema_is_valid_and_accepts_corpus():
    """Descriptions are not contract: the schema must still accept every archive.

    The structural content of the schema is exercised in full by the conformance
    runner (``test_conformance.py``); this is the cheap direct check that the
    manifest of every frozen corpus archive validates against the edited file.
    """
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(_schema_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    archives = sorted(_CORPUS.glob("*.qvf")) if _CORPUS.is_dir() else []
    if not archives:
        pytest.skip("conformance corpus not present (standalone checkout)")
    for archive in archives:
        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        errors = sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))
        assert not errors, f"{archive.name}: " + "; ".join(
            f"{list(e.path)}: {e.message}" for e in errors[:5]
        )
