# Contributing to QVF

QVF uses the toolset's existing
[contribution and verification process](https://github.com/vibe-qc/vibe-qc/blob/main/CONTRIBUTING.md).
Keep patches focused, explain the expected behavior, and include relevant
tests and conformance results. QVF contributions are under this repository's
**Apache-2.0** license; see [LICENSE](LICENSE).

Keep real machine configuration, credentials, account names and private
data outside the source tree. Enable the staged-content privacy hook once
per clone:

```sh
git config --local core.hooksPath .githooks
python3 .githooks/test_privacy_hook.py -q
```

Use documented placeholders for paths and RFC 5737 address ranges for
examples. The hook checks staged text, and does not replace the filename,
binary, secret and full-publication scans required before publishing a
snapshot. Report security and privacy issues privately per [SECURITY.md](SECURITY.md).

### Private operator configuration

Deployment configuration is maintained separately from the format source.
Private literal terms can be supplied to the contributor guard through
`VIBE_PRIVACY_TERMS_FILE` or clone-local `privacy.termsFile`. Use an absolute
path to a UTF-8 file outside every Git checkout and object database, one
literal per line. Matching is case-insensitive; an explicitly configured
missing, empty or in-repository file blocks the check, including symlinks
through a checkout. Never commit the private policy or resolved home paths.

Keep operator configuration and audit evidence in external private storage.
The toolset uses an absolute `VIBE_PRIVATE_ROOT`, defaulting to
`${XDG_STATE_HOME:-$HOME/.local/state}/vibe-private`; it must resolve outside
Git repositories. A terms file can live under `qvf/config/` in that root.
Set `VIBE_PRIVACY_TERMS_FILE` to its absolute path explicitly; QVF does not
create or discover private policy files automatically. Use owner-only
directories (0700) and files (0600), and keep credentials in your existing
secret store. Ordinary build outputs and caches are unaffected.
