# Public source snapshots

QVF's current source is portable and intended to be publishable without
content rewriting or file exclusions. Private operational configuration and
audit evidence belong outside product checkouts; see CONTRIBUTING.md.

Private development history remains private. The public repository uses a
separately constructed history containing only reviewed source snapshots.
Never mirror the development Git database directly or use a shallow clone
as a privacy boundary.

The publication process checks every committed source file, including its
path, bytes and mode, and scans all objects reachable from the selected
public refs. It adds PUBLIC_SOURCE_PROVENANCE.json to identify the original
source revision and PUBLIC_SOURCE_INVENTORY.json to record source and export
hashes. These two publication records are generated outside this checkout.
New snapshots must preserve all source bytes and modes; unresolved privacy
findings block publication.

Public commit IDs differ from development commit IDs. Historical releases
retain their separately reviewed snapshots. Corrections produce a new
snapshot or patch release; existing release tags are not rewritten. See
CONTRIBUTING.md for the existing contributor policy and SECURITY.md for
private security reporting.
