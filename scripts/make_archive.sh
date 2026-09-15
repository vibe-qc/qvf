#!/usr/bin/env bash
# Build local distributables from committed source, never checkout contents.
# Usage: scripts/make_archive.sh [--output-dir DIR]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLKIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${TOOLKIT_DIR}/dist"
if [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]; then
  echo 'Usage: scripts/make_archive.sh [--output-dir DIR]'
  echo 'Requires Git, Python 3 and clean committed source. Outputs remain local.'
  exit 0
fi
if [[ $# == 2 && $1 == --output-dir && -n $2 ]]; then
  DIST_DIR="$2"
elif [[ $# != 0 ]]; then
  echo 'Usage: scripts/make_archive.sh [--output-dir DIR]' >&2
  exit 2
fi

cd "${TOOLKIT_DIR}"
if [[ "$(git rev-parse --show-toplevel)" != "${TOOLKIT_DIR}" ]]; then
  echo 'Run from a standalone QVF Git checkout.' >&2
  exit 2
fi
SOURCE_COMMIT="$(git rev-parse --verify HEAD)"
if ! git diff --quiet --no-ext-diff --no-textconv "${SOURCE_COMMIT}" --; then
  echo 'Commit tracked changes before packaging.' >&2
  exit 2
fi
# Read the committed inventory directly. No attributes, checkout filters,
# untracked files or Git object database become distribution content.
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT
python3 - "${SOURCE_COMMIT}" "${STAGE_DIR}/source" <<'PYTHON'
from pathlib import Path, PurePosixPath
import subprocess
import sys

commit, destination = sys.argv[1], Path(sys.argv[2])
records = subprocess.check_output(["git", "ls-tree", "-rz", commit]).split(b"\0")
for record in filter(None, records):
    header, raw_path = record.split(b"\t", 1)
    mode, kind, oid = header.decode().split()
    path = PurePosixPath(raw_path.decode())
    if (mode not in {"100644", "100755"} or kind != "blob"
            or path.is_absolute() or any(p in {"..", ".git"} for p in path.parts)):
        raise SystemExit("Only regular source files may be packaged.")
    target = destination / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(subprocess.check_output(["git", "cat-file", "blob", oid]))
    target.chmod(int(mode, 8) & 0o777)
PYTHON
VERSION="$(tr -d '[:space:]' < "${STAGE_DIR}/source/VERSION")"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]; then
  echo 'Invalid committed VERSION.' >&2
  exit 2
fi
NAME="qvf-writer-${VERSION}"
# Check the actual archived bytes; never silently repair or mutate source.
python3 "${STAGE_DIR}/source/scripts/amalgamate.py" --check
cmp "${STAGE_DIR}/source/spec/qvf_manifest.schema.json" \
    "${STAGE_DIR}/source/python/qvf_manifest.schema.json"
mv "${STAGE_DIR}/source" "${STAGE_DIR}/${NAME}"
mkdir -p "${DIST_DIR}"
DIST_DIR="$(cd "${DIST_DIR}" && pwd)"
# Standard-library writers avoid embedding the local account in tar headers.
# Fixed metadata also makes repeated builds of the same tree byte-identical.
python3 - "${STAGE_DIR}" "${DIST_DIR}" "${NAME}" <<'PYTHON'
import gzip
import io
from pathlib import Path
import sys
import tarfile
import zipfile

stage, destination, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
with (destination / (name + ".tar.gz")).open("wb") as raw:
    with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for file in sorted((stage / name).rglob("*")):
                if file.is_file():
                    data = file.read_bytes()
                    info = tarfile.TarInfo(file.relative_to(stage).as_posix())
                    info.size = len(data)
                    info.mode = file.stat().st_mode & 0o777
                    archive.addfile(info, io.BytesIO(data))
with zipfile.ZipFile(destination / (name + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted((stage / name).rglob("*")):
        if file.is_file():
            info = zipfile.ZipInfo(file.relative_to(stage).as_posix())
            info.create_system = 3
            info.external_attr = (file.stat().st_mode & 0o777 | 0o100000) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, file.read_bytes())
PYTHON
echo "Packaged ${NAME} from ${SOURCE_COMMIT}. Artifacts remain in ${DIST_DIR}."
