"""mkdocs hooks of the QVF documentation site (Apache-2.0).

The site is built from ``docs/``, but the normative documents live at the
repository root and in ``spec/``, and every page links repository files by
their path in the checkout. These hooks keep the sources where they are:

* ``on_files`` adds the top-level documents of ``EXTRA_PAGES`` to the site;
* ``on_config`` gives headings GitHub/GitLab-style anchors, which the
  documents' ``#section`` links are written against;
* ``on_page_markdown`` resolves each relative link against the page's real
  path in the repository. A link to a site page becomes a link to that page;
  a link to any other existing repository file or directory points at the
  public source tree (``repo_url``). Other links stay as written, so
  ``mkdocs build --strict`` still reports them.

Fenced code blocks are left untouched.

``on_files`` also runs Doxygen over ``cpp/Doxyfile`` and adds its HTML under
``api/cpp-reference/`` of the site, linked from ``docs/api/cpp.md``. A
Doxygen warning is an mkdocs warning, so strict mode fails on it. Doxygen
must be on ``PATH`` (or named by ``DOXYGEN``); ``QVF_DOCS_NO_DOXYGEN=1``
builds the site with a placeholder page instead of the reference.
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile

from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

#: Repository documents outside docs/ that are site pages: {repo path: site path}.
EXTRA_PAGES = {
    "README.md": "index.md",
    "spec/qvf-format-spec.md": "spec/qvf-format-spec.md",
    "conformance/README.md": "conformance.md",
    "GOVERNANCE.md": "governance.md",
    "CHANGELOG.md": "changelog.md",
    "ROADMAP.md": "roadmap.md",
    "CONTRIBUTING.md": "contributing.md",
    "SECURITY.md": "security.md",
}

#: Where the Doxygen HTML lands in the site.
CPP_REFERENCE = "api/cpp-reference"

_log = logging.getLogger("mkdocs.hooks.qvf")
_doxygen_dirs: list[tempfile.TemporaryDirectory] = []

_LINK = re.compile(r"(\]\()([^)\s]+)(\))")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def slugify(value: str, separator: str = "-") -> str:
    """Heading anchor as GitHub and GitLab render it: lower case, characters
    other than word characters, hyphens and spaces dropped, each space a
    hyphen (runs are not collapsed)."""
    value = re.sub(r"[^\w\- ]", "", value.strip().lower())
    return value.replace(" ", separator)


def on_config(config):
    config["mdx_configs"].setdefault("toc", {})["slugify"] = slugify
    return config


def _site_map(config) -> dict[str, str]:
    """{repo path: site path} of every page of the site."""
    out = dict(EXTRA_PAGES)
    docs = os.path.relpath(config["docs_dir"], ROOT).replace(os.sep, "/")
    for dirpath, _dirs, names in os.walk(config["docs_dir"]):
        for name in names:
            if name.endswith(".md"):
                rel = os.path.relpath(os.path.join(dirpath, name), config["docs_dir"])
                rel = rel.replace(os.sep, "/")
                out[f"{docs}/{rel}"] = rel
    return out


def _run_doxygen(out_dir: str) -> str:
    """Run Doxygen into ``out_dir``; return the directory of its HTML."""
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
        version = fh.read().strip()
    with open(os.path.join(ROOT, "cpp", "Doxyfile"), encoding="utf-8") as fh:
        doxyfile = fh.read()
    filt = f'{sys.executable} {os.path.join(ROOT, "scripts", "doxygen_filter.py")}'
    doxyfile += (f'\nPROJECT_NUMBER = "{version}"\n'
                 f'OUTPUT_DIRECTORY = "{out_dir}"\n'
                 f'INPUT_FILTER = "{filt}"\n')
    exe = os.environ.get("DOXYGEN") or shutil.which("doxygen")
    if not exe:
        raise PluginError("Doxygen not found: install it (the C++/C API reference is "
                          "built from cpp/Doxyfile), name it with DOXYGEN=..., or set "
                          "QVF_DOCS_NO_DOXYGEN=1 to build without the reference")
    run = subprocess.run([exe, "-"], input=doxyfile, cwd=ROOT, capture_output=True,
                         text=True, check=False)
    for line in (run.stderr or "").splitlines():
        if line.strip():
            _log.warning("doxygen: %s", line.replace(ROOT + os.sep, ""))
    if run.returncode != 0:
        raise PluginError(f"doxygen failed with exit status {run.returncode}")
    return os.path.join(out_dir, "html")


def _placeholder(out_dir: str) -> str:
    html = os.path.join(out_dir, "html")
    os.makedirs(html)
    with open(os.path.join(html, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<!doctype html><meta charset=utf-8><title>QVF C++ and C API</title>"
                 "<p>This build skipped the Doxygen reference "
                 "(QVF_DOCS_NO_DOXYGEN). The headers are in cpp/include/qvf/.</p>\n")
    return html


def on_files(files, config):
    for repo_path, site_path in EXTRA_PAGES.items():
        files.append(File.generated(config, site_path,
                                    abs_src_path=os.path.join(ROOT, repo_path)))
    tmp = tempfile.TemporaryDirectory(prefix="qvf-doxygen-")
    _doxygen_dirs.append(tmp)       # removed in on_post_build
    html = (_placeholder(tmp.name) if os.environ.get("QVF_DOCS_NO_DOXYGEN")
            else _run_doxygen(tmp.name))
    for dirpath, _dirs, names in os.walk(html):
        for name in sorted(names):
            rel = os.path.relpath(os.path.join(dirpath, name), html).replace(os.sep, "/")
            files.append(File.generated(config, f"{CPP_REFERENCE}/{rel}",
                                        abs_src_path=os.path.join(dirpath, name)))
    return files


def on_post_build(config):
    while _doxygen_dirs:
        _doxygen_dirs.pop().cleanup()


def _rewrite(target: str, repo_page: str, site_page: str, pages: dict[str, str],
             repo_url: str) -> str:
    if target.startswith("#") or _SCHEME.match(target) or target.startswith("/"):
        return target
    path, sep, anchor = target.partition("#")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(repo_page), path))
    if resolved in pages:
        rel = posixpath.relpath(pages[resolved], posixpath.dirname(site_page) or ".")
        return rel + sep + anchor
    full = os.path.join(ROOT, resolved)
    if resolved.startswith("..") or not os.path.exists(full):
        return target
    kind = "tree" if os.path.isdir(full) else "blob"
    return f"{repo_url.rstrip('/')}/{kind}/main/{resolved}" + sep + anchor


def on_page_markdown(markdown, page, config, files):
    pages = _site_map(config)
    reverse = {site: repo for repo, site in pages.items()}
    site_page = page.file.src_uri
    repo_page = reverse.get(site_page)
    if repo_page is None:
        return markdown
    out, fenced = [], False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            line = _LINK.sub(lambda m: m.group(1) + _rewrite(
                m.group(2), repo_page, site_page, pages, config["repo_url"]) + m.group(3),
                line)
        out.append(line)
    return "\n".join(out)
