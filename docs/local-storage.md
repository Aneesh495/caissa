# Local storage

The local project limit is 5,000,000,000 bytes. The whole Mac limit is
400,000,000,000 used bytes. Count the checkout, Git history, dependencies,
builds, data, runs, temporary files and project caches elsewhere on this Mac.
Moving a directory elsewhere on the same disk does not reduce this total.

Historical datasets and experiment evidence belong in the private
`Aneesh495/caissa-archive` repository. They do not belong in this source
repository's Git objects. Do not clone the archive onto the laptop.

`tools/storage_archive.py` groups identical files by SHA256, streams tar and
gzip through bounded memory chunks, uploads exact private Git blobs and binds
them to an archive commit. It downloads and independently reconstructs every
object before removing any corresponding local file. The local restore catalog
records original paths, hashes, permissions and modification times. Raw process
logs, private files, current control receipts and the stopped parallel working
set stay local. The archive is storage transport, not a new experiment result
or complete public reproduction package.

The migration requires a prospective finite plan, closed timed ledgers and the
real exclusive host lease. A failed upload or reconstruction retains the
unverified originals. Existing failed experiments and cumulative limits remain
unchanged. The initial migration may begin above the new project limit to
reduce its existing footprint. Ordinary producers must fit the limit first.

To restore a small individual file, invoke the module from an installed or
explicitly selected source root with `restore --root /absolute/project/path
--path data/example/file`. Restoration refuses an existing destination and
checks both storage limits before writing. A file too large for the local limit
must be processed remotely. Do not restore whole datasets locally.

The original 5.349 GB restoration trace and its reconstructed duplicate were
independently hashed before their local paths were hardlinked. Both paths and
all content bytes were preserved. Later archival retains both original paths
in the restore catalog even when their content has one remote object.
