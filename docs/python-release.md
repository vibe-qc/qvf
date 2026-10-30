# Python package release

The first PyPI candidate is `qvf-writer==0.7.0rc1`. This is a Python-only
candidate from current source, including the optional PySCF adapter. It does
not modify toolkit v0.6.0, format version 1, or frozen consumers' pins. Python
package metadata and `qvf.__version__` identify the candidate; `VERSION` and
other language packages continue to identify the existing toolkit series.
A later coordinated toolkit release must reconcile all language versions.
The candidate has not yet been uploaded. Do not advertise an index install
as available until anonymous installation succeeds.

## Prepare and verify

From the repository root:

```sh
python -m pip install build twine
python -m build python --outdir /tmp/qvf-dist
python -m twine check --strict /tmp/qvf-dist/*
```

Use a fresh output directory. The default build makes an sdist, then builds
the wheel from that sdist, proving the source distribution is self-contained.
Inspect both archives: include the package, schema, LICENSE and NOTICE;
exclude caches, local configuration, credentials and operational records.
The sdist also includes the runnable tutorial. The wheel requires no native
compilation and no base dependencies.

Create a fresh environment, install the wheel with `--no-deps`, and run
`scripts/smoke_python_package.py` from outside the checkout with `python -I`.
Then install the wheel's `pyscf,validate` extras into a second fresh
environment and run the [tutorial](tutorials/pyscf-to-qvf.md), `qvf validate`,
`qvf-validate` and `pip check`. Record package hashes, source commit and tested
Python/PySCF versions. Existing adapter tests provide broader method coverage;
the tutorial is the installed-distribution acceptance check.

## One-time account setup

The maintainer creates/verifies a PyPI account with two-factor authentication,
then adds a **pending GitHub Trusted Publisher** at
<https://pypi.org/manage/account/publishing/>:

| Field | Value |
| --- | --- |
| PyPI project name | `qvf-writer` |
| GitHub owner | `vibyverse` |
| Repository | `qvf` |
| Workflow filename | `publish-python.yml` |
| Environment | `pypi` |

Configure the GitHub repository environment `pypi` with an appropriate release
reviewer. The workflow requests its short-lived OIDC identity only in the
publish job, which downloads the checked artifacts and runs no project code.
No API token or password needs to be shared with a contributor.
Pending publishers do not reserve names. See
[PyPI's pending publisher instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Publish after authorization

1. Freeze and qualify the exact Python candidate, including the relevant
   Python candidate checks. Preserve the existing toolkit tags and pins.
2. Land the clean candidate source on the canonical GitHub repository.
   Verify that the candidate includes this workflow and the exact qualified
   source. Do not push private pre-migration ancestry to the public repository.
3. Create the immutable public package tag `python-v0.7.0rc1` at that verified
   snapshot. This is a Python distribution tag, not a replacement toolkit tag.
4. Manually run **Python package release** from the trusted default branch,
   with `release_tag=python-v0.7.0rc1` and `publish=false` to build/check it.
   The workflow verifies the tag matches the package version.
5. After the maintainer authorizes upload, run with the same tag and
   `publish=true`, and approve the `pypi` environment. The workflow rebuilds
   and checks the exact tagged source before uploading those artifacts.
6. In another clean environment install
   `qvf-writer[pyscf,validate]==0.7.0rc1` from PyPI, rerun the tutorial, and
   verify the index files and hashes. Then update installation documentation
   from “prepared candidate” to “published candidate”.

A final `0.7.0` release needs its own versioned artifacts; never overwrite an
uploaded version. Base Python 3.9 support does not imply PySCF support on
every Python/platform combination. The workflow tests the optional adapter
on Linux/Python 3.13; report other verified platforms separately.
