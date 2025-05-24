# torrent-models

[![docs](https://readthedocs.org/projects/torrent-models/badge/)](https://torrent-models.readthedocs.io/en/latest/)

.torrent file parsing and creation with pydantic
(and models for other bittorrent things too)

While there are [many](#other-projects) other torrent packages, this one:

- Is simple and focused
- Can create and parse v1, v2, hybrid, and [other BEPs](./beps.md)
- Is focused on library usage (but does [cli things too](./usage/cli.md))
- Validates torrent files (e.g. when accepting them as user input!)
- Treats .torrent files as an *extensible* rather than fixed format
- Is performant! (and asyncio compatible when hashing!)
- Uses python typing and is mypy friendly

~ alpha software primarily intended for use with [sciop](https://codeberg.org/Safeguarding/sciop) ~


## See also

These are also good projects, and probably more battle tested
(but we don't know them well and can't vouch for their use):

- [`torrentfile`](https://alexpdev.github.io/torrentfile/)
- [`dottorrent`](https://dottorrent.readthedocs.io)
- [`torf`](https://github.com/rndusr/torf)
- [`torrenttool`](https://github.com/idlesign/torrentool)
- [`PyBitTorrent`](https://github.com/gaffner/PyBitTorrent)
- [`torrent_parser`](https://github.com/7sDream/torrent_parser)

Specifically
- `torf` has some notable performance problems, and doesn't support v2
- `torrentfile` is focused on the cli and doesn't appear to be able to validate torrent files, 
  and there is no dedicated method for parsing them, 
  e.g. editing [directly manipulates the bencoded dict](https://github.com/alexpdev/torrentfile/blob/d50d942dc72c93f052c63b443aaec38c592a14df/torrentfile/edit.py#L65)
  and [rebuilding requires the files to be present](https://github.com/alexpdev/torrentfile/blob/d50d942dc72c93f052c63b443aaec38c592a14df/torrentfile/rebuild.py)
- `dottorrent` can only write, not parse torrent files.
- `torrenttool` doesn't validate torrents
- `PyBitTorrent` doesn't validate torrents
- `torrent_parser` doesn't validate torrents and doesn't have a torrent file class