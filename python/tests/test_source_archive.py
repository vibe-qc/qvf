"""Exercise distribution boundaries with real archives and disposable Git state."""
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


@pytest.fixture
def repo(tmp_path):
    checkout = tmp_path / "source"
    subprocess.run(["git", "clone", "--no-local", "-q", str(ROOT), str(checkout)], check=True)
    # Run the current implementation even before the source fix is committed.
    shutil.copyfile(ROOT / "scripts/make_archive.sh", checkout / "scripts/make_archive.sh")
    git(checkout, "config", "user.name", "Archive test")
    git(checkout, "config", "user.email", "archive@example.invalid")
    git(checkout, "add", "scripts/make_archive.sh")
    git(checkout, "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "Test archive builder")
    return checkout


def run(repo, *args):
    return subprocess.run(["bash", str(repo / "scripts/make_archive.sh"), *args],
                          capture_output=True, text=True)


def test_archive_excludes_checkout_state_and_preserves_corpus(repo):
    sentinel = "-".join(("synthetic", "private", "archive", "marker"))
    for name in (".env", ".git/private-evidence", ".cache/private", "build-cpp/private", "python/__pycache__/private.pyc"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sentinel)
    neighbor = repo.parent / "docs/_static/downloads"
    neighbor.mkdir(parents=True)
    output = repo.parent / "output with spaces"
    result = run(repo, "--output-dir", str(output))
    assert result.returncode == 0, result.stderr + result.stdout
    expected = set(git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
    with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
        assert all(m.uid == 0 and m.gid == 0 and not m.uname and not m.gname
                   and m.mtime == 0 for m in archive.getmembers())
        files = {m.name.split("/", 1)[1]: archive.extractfile(m).read()
                 for m in archive.getmembers() if m.isfile()}
    assert set(files) == expected
    assert len([p for p in files if p.endswith(".qvf")]) == 12
    assert not any(sentinel.encode() in b for b in files.values())
    for path, data in files.items():
        assert data == subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:" + path])
    assert not list(neighbor.iterdir())
    with zipfile.ZipFile(next(output.glob("*.zip"))) as archive:
        zipped = {m.filename.split("/", 1)[1]: archive.read(m)
                  for m in archive.infolist() if not m.is_dir()}
    assert zipped == files
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert run(repo, "--output-dir", str(output)).returncode == 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_dirty_tracked_source_is_rejected(repo):
    with (repo / "README.md").open("a") as stream:
        stream.write("\nUncommitted change\n")
    result = run(repo)
    assert result.returncode != 0
    assert "Commit tracked changes" in result.stderr
    assert not (repo / "dist").exists()


@pytest.mark.parametrize("path", ["python/qvf_manifest.schema.json", "cpp/qvf_single.hpp"])
def test_committed_generated_drift_is_rejected(repo, path):
    with (repo / path).open("a") as stream:
        stream.write("\n")
    git(repo, "add", path)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Test generated drift")
    assert run(repo).returncode != 0
    assert not (repo / "dist").exists()


def test_committed_symlink_is_rejected(repo):
    (repo / "linked-source").symlink_to("README.md")
    git(repo, "add", "linked-source")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Test source symlink")
    result = run(repo)
    assert result.returncode != 0
    assert "Only regular source files" in result.stderr


def test_invalid_output_option_is_rejected(repo):
    assert run(repo, "--output-dir").returncode == 2
    assert run(repo, "--output-dir", "").returncode == 2
