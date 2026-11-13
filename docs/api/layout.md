---
myst:
    enable_extensions: ["colon_fence"]
---

# `layout`

{attr}`.Torrent.layout` maps between files and the pieces that contain their data,
e.g. to download and check only the pieces you need for one file.

## Examples

Make a torrent with three files and 32 KiB pieces,
and a fixed-width [rich](https://rich.readthedocs.io) console to print with:

```pycon
>>> import random
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from rich.console import Console
>>> from torrent_models import KiB, TorrentCreate
>>> console = Console(width=80, color_system=None)
>>> tmp = TemporaryDirectory()
>>> root = Path(tmp.name) / "my_torrent"
>>> root.mkdir()
>>> for name, size in {"a.bin": 20 * KiB, "b.bin": 40 * KiB, "c.bin": 10 * KiB}.items():
...     _ = (root / name).write_bytes(random.randbytes(size))
>>> create = TorrentCreate(path_root=root, piece_length=32 * KiB)

```

::::{tab-set}

:::{tab-item} v1

In v1 torrents, files are laid end to end and split into pieces,
so a piece can hold data from several files.
Each {class}`~torrent_models.types.v1.V1PieceRange` lists the byte range of each file in the piece,
and the piece's `offset` within the whole torrent.

`b.bin` starts in piece 0 after `a.bin`, and ends in piece 1 before `c.bin`:

```pycon
>>> torrent = create.generate("v1")
>>> console.print(torrent.layout.file_pieces("b.bin"))
[
    V1PieceRange(
        piece_idx=0,
        piece_length=32768,
        ranges=[
            FileItemRange(
                length=20480,
                path=['a.bin'],
                attr=None,
                range_start=0,
                range_end=20480,
                full_path='my_torrent/a.bin'
            ),
            FileItemRange(
                length=40960,
                path=['b.bin'],
                attr=None,
                range_start=0,
                range_end=12288,
                full_path='my_torrent/b.bin'
            )
        ],
        piece_hash=...,
        offset=0
    ),
    V1PieceRange(
        piece_idx=1,
        piece_length=32768,
        ranges=[
            FileItemRange(
                length=40960,
                path=['b.bin'],
                attr=None,
                range_start=12288,
                range_end=40960,
                full_path='my_torrent/b.bin'
            ),
            FileItemRange(
                length=10240,
                path=['c.bin'],
                attr=None,
                range_start=0,
                range_end=4096,
                full_path='my_torrent/c.bin'
            )
        ],
        piece_hash=...,
        offset=32768
    )
]

```

Get a single piece by its index, and check data against it:

```pycon
>>> piece = torrent.layout.v1_piece_range(1)
>>> console.print(piece)
V1PieceRange(
    piece_idx=1,
    piece_length=32768,
    ranges=[
        FileItemRange(
            length=40960,
            path=['b.bin'],
            attr=None,
            range_start=12288,
            range_end=40960,
            full_path='my_torrent/b.bin'
        ),
        FileItemRange(
            length=10240,
            path=['c.bin'],
            attr=None,
            range_start=0,
            range_end=4096,
            full_path='my_torrent/c.bin'
        )
    ],
    piece_hash=...,
    offset=32768
)
>>> data = []
>>> for r in piece.ranges:
...     with open(root / "/".join(r.path), "rb") as f:
...         _ = f.seek(r.range_start)
...         data.append(f.read(r.range_end - r.range_start))
>>> piece.validate_data(data)
True

```

:::

:::{tab-item} v2

In v2 torrents, each file starts on a new piece, so a piece only holds data from one file.
Pieces are numbered across the whole torrent in file tree order:
`a.bin` is piece 0, `b.bin` is pieces 1 and 2, and `c.bin` is piece 3.
Each {class}`~torrent_models.types.v2.V2PieceRange` is a byte range within one file,
with its index within the torrent (`piece_idx`) and within the file (`file_piece_idx`).

```pycon
>>> torrent = create.generate("v2")
>>> console.print(torrent.layout.file_pieces("b.bin"))
[
    V2PieceRange(
        piece_idx=1,
        piece_length=32768,
        path='b.bin',
        file_piece_idx=0,
        range_start=0,
        range_end=32768,
        file_size=40960,
        piece_hash=...,
        root_hash=...,
        full_path='my_torrent/b.bin'
    ),
    V2PieceRange(
        piece_idx=2,
        piece_length=32768,
        path='b.bin',
        file_piece_idx=1,
        range_start=32768,
        range_end=40960,
        file_size=40960,
        piece_hash=...,
        root_hash=...,
        full_path='my_torrent/b.bin'
    )
]

```

Files no longer than one piece have a single range for the whole file,
which is checked against the file's root hash rather than a piece hash:

```pycon
>>> console.print(torrent.layout.v2_piece_range("a.bin"))
V2PieceRange(
    piece_idx=0,
    piece_length=32768,
    path='a.bin',
    file_piece_idx=0,
    range_start=0,
    range_end=20480,
    file_size=20480,
    piece_hash=None,
    root_hash=...,
    full_path='my_torrent/a.bin'
)

```

Get a single piece by its path and index within the file, and check data against it:

```pycon
>>> piece = torrent.layout.v2_piece_range("b.bin", 1)
>>> console.print(piece)
V2PieceRange(
    piece_idx=2,
    piece_length=32768,
    path='b.bin',
    file_piece_idx=1,
    range_start=32768,
    range_end=40960,
    file_size=40960,
    piece_hash=...,
    root_hash=...,
    full_path='my_torrent/b.bin'
)
>>> data = (root / "b.bin").read_bytes()[piece.range_start : piece.range_end]
>>> piece.validate_data(data)
True

```

Or get it by its index within the whole torrent, which is how peers refer to pieces:

```pycon
>>> torrent.layout.v2_piece_range_at(2) == piece
True

```

:::

:::{tab-item} hybrid

Hybrid torrents have both v1 and v2 pieces.
{meth}`~torrent_models.layout.FileLayout.file_pieces` gives v2 piece ranges:

```pycon
>>> torrent = create.generate("hybrid")
>>> console.print(torrent.layout.file_pieces("b.bin"))
[
    V2PieceRange(
        piece_idx=1,
        piece_length=32768,
        path='b.bin',
        file_piece_idx=0,
        range_start=0,
        range_end=32768,
        file_size=40960,
        piece_hash=...,
        root_hash=...,
        full_path='my_torrent/b.bin'
    ),
    V2PieceRange(
        piece_idx=2,
        piece_length=32768,
        path='b.bin',
        file_piece_idx=1,
        range_start=32768,
        range_end=40960,
        file_size=40960,
        piece_hash=...,
        root_hash=...,
        full_path='my_torrent/b.bin'
    )
]

```

Use {meth}`~torrent_models.layout.FileLayout.v1_file_pieces` for the v1 pieces.
Hybrid torrents pad every file to a piece boundary with padfiles,
so their v1 pieces have the same indices as their v2 pieces:
`b.bin` starts at the beginning of piece 1, after `a.bin` and its padding,
and the padfile after it fills the rest of piece 2:

```pycon
>>> console.print(torrent.layout.v1_file_pieces("b.bin"))
[
    V1PieceRange(
        piece_idx=1,
        piece_length=32768,
        ranges=[
            FileItemRange(
                length=40960,
                path=['b.bin'],
                attr=None,
                range_start=0,
                range_end=32768,
                full_path='my_torrent/b.bin'
            )
        ],
        piece_hash=...,
        offset=32768
    ),
    V1PieceRange(
        piece_idx=2,
        piece_length=32768,
        ranges=[
            FileItemRange(
                length=40960,
                path=['b.bin'],
                attr=None,
                range_start=32768,
                range_end=40960,
                full_path='my_torrent/b.bin'
            ),
            FileItemRange(
                length=24576,
                path=['.pad', '24576'],
                attr=b'p',
                range_start=0,
                range_end=24576,
                full_path='my_torrent/.pad/24576'
            )
        ],
        piece_hash=...,
        offset=65536
    )
]

```

:::

::::

## API

```{eval-rst}
.. automodule:: torrent_models.layout
    :members:
    :undoc-members:
```
