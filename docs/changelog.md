# Changelog

## v0.3.*

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
