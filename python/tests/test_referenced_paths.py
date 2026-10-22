"""Reference guard: every repository path the governance documents name exists.

GOVERNANCE.md, registry.json, README.md and ROADMAP.md point readers at other
files and directories (a changelog, a legacy schema, the planning documents).
A reference to something that was never created is a defect (format review
D10), so this test extracts each file-like reference and asserts it exists
relative to the repository root.

What counts as a file reference:

* Markdown documents: a backtick-quoted token or a link target that ends in one
  of ``EXTENSIONS`` or in ``/`` (a directory). Fenced code blocks are examples,
  not references, and are ignored.
* registry.json: the same rule applied to every whitespace-separated word of
  every string value, because the registry names files in plain prose.

URLs, ``#anchors``, bare extensions (``.cpp``) and anything containing
characters that cannot occur in a plain relative path (globs, placeholders) are
skipped. ``.qvf`` is deliberately not in ``EXTENSIONS``: names such as
``h2o.qvf`` are examples of output, not repository files. The few quoted names
that look like paths but are not committed files are listed, with the reason,
in ``NOT_REPOSITORY_FILES``.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ["GOVERNANCE.md", "registry.json", "README.md", "ROADMAP.md"]
EXTENSIONS = (".md", ".json", ".py", ".hpp", ".h", ".cpp", ".cff", ".sh")

# Names the documents quote that look like paths but are not committed files.
NOT_REPOSITORY_FILES = {
    "dist/": "build output directory created by scripts/make_archive.sh",
    "manifest.json": "the manifest member inside every .qvf archive",
}

_FENCED_BLOCK = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
_CODE_SPAN = re.compile(r"`([^`\s]+)`")
_PLAIN_PATH = re.compile(r"[\w./-]+")


def _as_reference(token):
    """Return the repository-relative path named by ``token``, or None."""
    token = token.split("#", 1)[0]
    if not token or token.startswith("/") or "://" in token:
        return None
    if not _PLAIN_PATH.fullmatch(token) or token in EXTENSIONS:
        return None  # a bare extension such as `.cpp` names a file type
    if token in NOT_REPOSITORY_FILES:
        return None
    if token.endswith("/") or token.endswith(EXTENSIONS):
        return token
    return None


def _json_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _json_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _json_strings(value)


def _tokens(name, text):
    if name.endswith(".json"):
        for string in _json_strings(json.loads(text)):
            for word in string.split():
                yield word.strip("`'\"()[],;:").rstrip(".")
    else:
        text = _FENCED_BLOCK.sub("", text)
        yield from _LINK_TARGET.findall(text)
        yield from _CODE_SPAN.findall(text)


def extract_references(name, text):
    """Sorted, de-duplicated repository-relative references in a document."""
    found = {_as_reference(token) for token in _tokens(name, text)}
    return sorted(found - {None})


def test_extractor_rules():
    text = (
        "See [the spec](spec/qvf-format-spec.md#section) and `docs/`, "
        "or [site](https://example.com/a.md) and [top](#top). "
        "Writes `h2o.qvf`; globs like `spec/*.json` and `{name}.py` are skipped, "
        "as are the bare extension `.cpp`, `dist/` and `manifest.json`.\n"
        "```sh\n"
        "python tools/example.py\n"
        "```\n"
    )
    assert extract_references("sample.md", text) == [
        "docs/",
        "spec/qvf-format-spec.md",
    ]
    registry = json.dumps({"note": "see GOVERNANCE.md; and CHANGELOG.md."})
    assert extract_references("sample.json", registry) == [
        "CHANGELOG.md",
        "GOVERNANCE.md",
    ]


@pytest.mark.parametrize("name", DOCUMENTS)
def test_referenced_paths_exist(name):
    document = ROOT / name
    if not document.exists():
        pytest.skip(f"{name} not present (standalone checkout)")
    references = extract_references(name, document.read_text(encoding="utf-8"))
    assert references, f"{name}: no file references found; the extractor is broken"
    missing = [ref for ref in references if not (ROOT / ref).exists()]
    assert not missing, f"{name} references paths that do not exist: {missing}"
