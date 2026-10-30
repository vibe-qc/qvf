# Source hosting and publication

[github.com/vibyverse/qvf](https://github.com/vibyverse/qvf) is the canonical
home for QVF development, issues, pull requests and releases. The former
GitLab project is retained as a read-only historical archive.

The transition preserves the existing public GitHub history and immutable
release tags. Earlier public snapshots have different commit identities from
their private development source. Their provenance and inventory records
remain in those historical commits. Current GitHub-native commits are the
source identities; they do not require a separate mirror or snapshot publisher.

Private pre-migration history and project records are preserved separately
with restricted access. Never merge that private ancestry into this public
repository or use a shallow clone as a privacy boundary.

Keep committed source public-safe, including filenames, binary fixtures,
metadata and commit messages. Keep operational configuration, credentials and
audit evidence outside product checkouts. Enable the privacy hook and follow
CONTRIBUTING.md and SECURITY.md. Unresolved privacy findings block publication.

Development commits use focused checks and skip full CI. Authorized release
candidates run the GitHub candidate workflow. Registry uploads require explicit
release authorization; changing hosts does not publish a package, change the
format version or update consumer pins. Existing release tags are not rewritten.
