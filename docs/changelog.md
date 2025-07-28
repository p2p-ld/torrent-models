# Changelog

## v0.2.*

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