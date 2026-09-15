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
path to a UTF-8 file outside the checkout, one literal per line. Matching is
case-insensitive; an explicitly configured missing, empty or in-tree file
blocks the check. Never commit the private policy or resolved home paths.
