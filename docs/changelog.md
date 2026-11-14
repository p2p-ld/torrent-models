# Changelog

## v0.6.*

### v0.6.0

**Breaking**

- {meth}`.FileTree.from_trees` and {meth}`.PieceLayers.from_trees` take the paths of every file
  in the torrent, as well as their merkle trees, since empty files have no merkle tree.

**Fixed**

- Empty files are in the file trees of created v2 and hybrid torrents, with a `length` of 0
  and no `pieces root`, like libtorrent makes them. They used to be left out of the file tree,
  so v2 torrents were missing them, and creating a hybrid torrent with an empty file failed
  because its v1 file list and v2 file tree didn't match.

## v0.5.*

### v0.5.0

**Breaking**

- {class}`~torrent_models.types.v2.V2PieceRange`'s `piece_idx` is now the piece's index
  within the whole torrent, which is how peers refer to pieces, like
  {class}`~torrent_models.types.v1.V1PieceRange`'s `piece_idx`.
  In v2 torrents, each file starts on a new piece, and pieces are numbered across the torrent
  in file tree order (BEP 52).
  It used to be the index of the piece within its file, which is now `file_piece_idx`.
  In hybrid torrents, v1 and v2 pieces of the same data now have the same index.
- The second argument of {meth}`~torrent_models.layout.FileLayout.v2_piece_range`
  is renamed from `piece_idx` to `file_piece_idx`. It still takes the index within the file.

**Added**

- {meth}`~torrent_models.layout.FileLayout.v2_piece_range_at` gets a v2 piece range
  from its index within the whole torrent.
- {meth}`~torrent_models.layout.FileLayout.piece_range` gets a piece range from its index,
  using v2 piece ranges for v2 and hybrid torrents and v1 piece ranges for v1 torrents.
- {attr}`~torrent_models.layout.FileLayout.n_pieces` is the number of pieces in the torrent.
- `size` on {class}`~torrent_models.types.v1.V1PieceRange`
  and {class}`~torrent_models.types.v2.V2PieceRange` is the number of bytes in the piece.
- `padding` on piece ranges is the number of bytes of padfiles at the end of the piece,
  which clients needn't download (BEP 47). It's always 0 for v2 piece ranges.
- {meth}`~torrent_models.layout.FileLayout.file` gets a file by its path,
  as in {attr}`.Torrent.files`.
- `download_path` on {class}`~torrent_models.types.common.GenericFileItem` is where the file
  goes, relative to the download directory: in a directory named after the torrent,
  unless it's the torrent's only file.
- {meth}`.Torrent.check` says whether a torrent's data is on disk and matches its hashes.
  `read` on piece ranges reads a piece's data.
  Both raise ValueError for a path in the torrent that would lead outside the directory.
- {func}`.safe_join` joins a path from a torrent or archive onto a directory,
  refusing paths that would end up outside of it.
- {meth}`.FileItem.padfile` makes a padfile, named `.pad/{length}`.
- {meth}`~torrent_models.layout.FileLayout.byte_range_pieces`,
  {meth}`~torrent_models.layout.FileLayout.v1_byte_range_pieces` and
  {meth}`~torrent_models.layout.FileLayout.v2_byte_range_pieces` get the pieces that hold
  bytes `[start, end)` of a file, preferring v2 piece ranges like
  {meth}`~torrent_models.layout.FileLayout.file_pieces`. They raise IndexError
  for a range outside of the file, and ValueError for a file that isn't in the torrent.
- A `py.typed` marker, so type checkers use torrent-models' type hints.

**Changed**

- `validate_data` on piece ranges accepts data split up any way that adds up to the piece,
  like 16 KiB blocks as peers send them, or as one `bytes`. v1 piece ranges used to need
  one chunk per file range, and v2 piece ranges 16 KiB blocks.
  The padfiles at the end of a v1 piece can be left out, and are filled in with zeros.
  It also accepts the directory the torrent was downloaded to, and checks the piece's data
  there, which is False if any of it isn't on disk.

**Fixed**

- {attr}`.Torrent.n_files`, {attr}`.Torrent.total_size` and the printed file list
  left out padfiles only when their `attr` was exactly `p`, so a padfile with other
  attributes too, like `px`, was counted as a file.
- {meth}`~torrent_models.layout.FileLayout.v2_piece_range` with a negative `file_piece_idx`
  counted back from the end of the file and gave the wrong piece.
  It now raises IndexError for any index outside of the file.

## v0.4.*

### v0.4.0

**Added**

[`#16`](https://github.com/p2p-ld/torrent-models/pull/16) 

Added {class}`~torrent_models.layout.FileLayout`, accessed as {attr}`.Torrent.layout`,
which maps between files and the pieces that contain their data -
e.g. to download only the pieces needed for one file in a torrent.

- {meth}`~torrent_models.layout.FileLayout.v1_file_pieces` and
  {meth}`~torrent_models.layout.FileLayout.v2_file_pieces` get all the piece ranges for a file
  from its path within the torrent.
- {meth}`~torrent_models.layout.FileLayout.file_pieces` does the same,
  using v2 piece ranges for v2 and hybrid torrents and v1 piece ranges for v1 torrents.
- {meth}`~torrent_models.layout.FileLayout.v1_piece_range` and
  {meth}`~torrent_models.layout.FileLayout.v2_piece_range` moved here from {class}`.Torrent`.
- All piece ranges have a `piece_length` -
  {class}`~torrent_models.types.v1.V1PieceRange` now has one, as well as an `offset`:
  the byte offset of the start of the piece within the whole torrent.

**Performance**

- [`#16`](https://github.com/p2p-ld/torrent-models/pull/16) `v1_piece_range` now finds the file where a piece starts with a binary search
over cached file offsets, rather than scanning the whole file list for every piece.

**Deprecated**

`Torrent.v1_piece_range` and `Torrent.v2_piece_range` raise a `DeprecationWarning`
and will be removed in a future version - use `torrent.layout.v1_piece_range`
and `torrent.layout.v2_piece_range` instead.
The file argument to `v2_piece_range` is named `path` in the new version.

## v0.3.*

### v0.3.4 - 2025-10-06

**Bugfix**

- Fix serialization of hashes in `print` mode, which now prints the hex-encoded version everywhere
- Add humanize to required deps

### v0.3.3 - 2025-09-30

**Bugfix**

Fixed the cli `torrent make` command, which was using the old `files` and `creator` convenience fields.

### v0.3.2 - 2025-08-21

**Bugfix**

[#9](https://github.com/p2p-ld/torrent-models/pull/9) - Fixed incorrectly finding start of piece
using modulo rather than subtraction, which could cause duplicate/incorrect ranges
in the cae that e.g. multiple files that were exactly piece length were at the start of a torrent.

### v0.3.1 - 2025-08-04

[#8](https://github.com/p2p-ld/torrent-models/pull/8)

**Features**
By the time we have piece ranges, 
we don't know about the torrent `info.name` field anymore, so we can't construct URLs accurately.

Give that responsibility to the relevant piece range classes, 
giving them a `webseed_url` method that can be used to get the full url to request from some url that's used as a webseed.

so e.g. for a multi-file torrent named `my_torrent` with a file `a.exe`, 
a webseed given as `https://example.com/data/` should have the file stored at `https://example.com/data/my_torrent/a.exe`

**Bugfix**

this also fixes v1-only single file torrents 
(a rare and discouraged case) which improperly added the metadata to the `files` list, 
rather than just having `name` and `length`.

### v0.3.0 - 2025-07-28

[#6](https://github.com/p2p-ld/torrent-models/pull/6) 
Add ability to get v1 and v2 byte ranges to validate partial data against.

The behavior differs somewhat significantly between v1 and v2, so we made separate implementations for both

- v1: {meth}`.Torrent.v1_piece_range` a piece may correspond to a range within a single file or across several, and may include padfiles that shouldn't really "exist" on a filesystem
- v2: {meth}`.Torrent.v2_piece_range` much simpler, a file either has a single root hash or a set of hashes from a lower level of the merkle tree, both are computed identically. pieces are always either a whole file or a part of a single file.

These correspond to the models returned, which both have a {meth}`~torrent_models.types.common.PieceRange.validate_data` method:

- v1: {class}`~torrent_models.types.v1.V1PieceRange`
- v2: {class}`~torrent_models.types.v2.V2PieceRange`

So we have two methods to get v1 and v2 ranges, which return a PieceRange object that can validate data passed to `validate_data`

so e.g. if we have a v1 torrent of 5 10KiB files of all zeros, and a piece size of 32 KiB, we might do somethign like this

```python
piece_range = torrent.v1_piece_range(0)
piece_range.validate_data([bytes(10), bytes(10), bytes(10), bytes(2)])
```

and v2 torrents work at the block level, as they usually do, so if we had a single-file v2 torrent with an empty 64 KiB file with a piece size of 64KiB, we would do

```python
piece_range = torrent.v2_piece_range('filename')
piece_range.validate_data([bytes(16 * KiB) for _ in range(4)])
```

#### Breaking

- changed the behavior of v2 piece layers dict to match v1 pieces: 
  when in memory, we split up the pieces into a list of hashes, rather than one bigass bytestring, 
  and then split again on serialization.

## v0.2.*

### v0.2.1 - 2025-07-27

bugfix
- raise error in clean_files when files are missing or misspecified, 
- rather than allowing to fall through to the generation process.

perf:
- cache computed infohashes rather than computing fresh each time.

### v0.2.0 - 2025-07-27

Version deployed with initial integration with sciop

breaking:
- {attr}`.InfoDictV1.v1_infohash` and {attr}`.InfoDictV2.v2_infohash` now return hex-encoded strings
  rather than bytes, because they are more commonly used than the `bytes` representation
- Remove async file i/o while hashing, see perf.

perf:
- Added parallel hashing codepath for cpu == 1 because making pools takes forever 
  when making many small torrents, e.g. in testing
- hashing switched from async to sync because async was significantly slower for unclear benefit

internal changes:
- n_processors defaults to 1 rather than `ncpus` until perf problems can be resolved

deps:
- remove `anyio`
- remove `nest-asyncio`

### v0.1.2 - 2025-07-25

quick iterations while integrating with sciop

- Add convenience properties for accessing trackers and files
- Allow trackerless torrents

### v0.1.1 - 2025-07-25

Preparing to swap in for sciop, where it will get real field testing.
Basic creation and validation systems work and have been validated against a corpus of
torrents in the wild.

Changelog will now actually contain meaningful changes, since the package is now considered
out of experimental phase and in beta.

## v0.0.*

### v0.0.2 - 2025-05-24

- Bugfix: force absolute paths in path_roots
- Docs: exist

### v0.0.1 - Start of package

Hello world, we have torrent models and hashing :)
