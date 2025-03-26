# torrent-pyd
.torrent file parsing and creation with pydantic

~ alpha software primarily intended for use with [sciop](https://codeberg.org/Safeguarding/sciop) ~

## Initial development

- [ ] Parsing
  - [ ] v1
  - [ ] v2
- [ ] Generation

## See also

These are also good projects, and certainly more battle tested:

- [`torrentfile`](https://alexpdev.github.io/torrentfile/)
- [`dottorrent`](https://dottorrent.readthedocs.io)
- [`torf`](https://github.com/rndusr/torf)

The only reason we didn't use them is because we wanted something
- that could handle v1, v2, hybrid, and a smattering of other BEPs
- focused on library usage
- simple
- performant
- modern python typing support