import hashlib
import random
from pathlib import Path

import pytest

from torrent_models import KiB, Torrent, TorrentCreate, safe_join
from torrent_models.types.v1 import FileItemRange, V1PieceRange
from torrent_models.types.v2 import V2PieceRange

from .conftest import DATA_DIR


def test_v1_piece_range_offset():
    """v1 piece ranges know their byte offset within the whole torrent"""
    piece = V1PieceRange(piece_idx=3, piece_length=32 * KiB, ranges=[], piece_hash=bytes(20))
    assert piece.offset == 96 * KiB


def test_v1_piece_range_size():
    """A v1 piece's size counts every file range in it, padfiles included"""
    ranges = [
        FileItemRange(
            length=10 * KiB, path=["a"], range_start=4 * KiB, range_end=10 * KiB, full_path="t/a"
        ),
        FileItemRange(
            length=6 * KiB,
            path=[".pad", "6144"],
            attr=b"p",
            range_start=0,
            range_end=6 * KiB,
            full_path="t/.pad/6144",
        ),
        FileItemRange(
            length=50 * KiB, path=["b"], range_start=0, range_end=20 * KiB, full_path="t/b"
        ),
    ]
    piece = V1PieceRange(piece_idx=0, piece_length=32 * KiB, ranges=ranges, piece_hash=bytes(20))
    assert piece.size == 32 * KiB


def test_v1_piece_range_padding():
    """Only padfiles at the end of a piece count as its padding, whatever other attrs they have"""
    a = FileItemRange(
        length=10 * KiB, path=["a"], range_start=0, range_end=10 * KiB, full_path="t/a"
    )
    pad = FileItemRange(
        length=6 * KiB,
        path=[".pad", "6144"],
        attr=b"hp",
        range_start=0,
        range_end=6 * KiB,
        full_path="t/.pad/6144",
    )
    b = FileItemRange(
        length=16 * KiB, path=["b"], range_start=0, range_end=16 * KiB, full_path="t/b"
    )

    def piece(*ranges: FileItemRange) -> V1PieceRange:
        return V1PieceRange(
            piece_idx=0, piece_length=32 * KiB, ranges=list(ranges), piece_hash=bytes(20)
        )

    assert piece(b, a, pad).padding == 6 * KiB
    assert piece(a, pad, b).padding == 0
    assert piece(b, a).padding == 0


def test_v1_validate_data_padding():
    """The padding at the end of a piece can be given as zeros, or left out"""
    a_data, b_data = random.randbytes(10 * KiB), random.randbytes(10 * KiB)
    a = FileItemRange(
        length=10 * KiB, path=["a"], range_start=0, range_end=10 * KiB, full_path="t/a"
    )
    b = FileItemRange(
        length=10 * KiB, path=["b"], range_start=0, range_end=10 * KiB, full_path="t/b"
    )

    def pad(length: int) -> FileItemRange:
        return FileItemRange(
            length=length,
            path=[".pad", str(length)],
            attr=b"p",
            range_start=0,
            range_end=length,
            full_path=f"t/.pad/{length}",
        )

    piece = V1PieceRange(
        piece_idx=0,
        piece_length=32 * KiB,
        ranges=[a, pad(6 * KiB), b, pad(6 * KiB)],
        piece_hash=hashlib.sha1(a_data + bytes(6 * KiB) + b_data + bytes(6 * KiB)).digest(),
    )
    assert piece.validate_data([a_data, bytes(6 * KiB), b_data, bytes(6 * KiB)])
    assert piece.validate_data([a_data, bytes(6 * KiB), b_data])
    assert not piece.validate_data([random.randbytes(10 * KiB), bytes(6 * KiB), b_data])
    # only the padding at the end can be left out
    with pytest.raises(AssertionError):
        piece.validate_data([a_data, b_data])


def test_v2_piece_range_size():
    """The last piece of a v2 file is as long as what's left of the file"""
    piece = V2PieceRange(
        piece_idx=2,
        file_piece_idx=2,
        path="a",
        range_start=64 * KiB,
        range_end=70 * KiB,
        piece_length=32 * KiB,
        file_size=70 * KiB,
        piece_hash=bytes(32),
        root_hash=bytes(32),
        full_path="t/a",
    )
    assert piece.size == 6 * KiB
    assert piece.padding == 0


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_webseed_url_singlefile(version: str, tmp_path: Path):
    """
    Webseed urls for piece ranges in a single file should be direct links to the file
    """
    tfile = tmp_path / "my_cool_file.exe"
    ws_url = "https://example.com/data/my_cool_file.exe"
    with open(tfile, "wb") as f:
        f.write(random.randbytes((32 * KiB) * 4))

    t = TorrentCreate(paths=[tfile], path_root=tmp_path, piece_length=32 * KiB).generate(
        version=version
    )
    if version == "v1":
        assert t.info.files is None
        v1_range = t.layout.v1_piece_range(2)
        prange = v1_range.ranges[0]
    else:
        assert len(t.flat_files) == 1
        prange = t.layout.v2_piece_range("my_cool_file.exe", 2)

    # direct links should be unchanged
    assert prange.webseed_url(ws_url) == ws_url
    # file should be appended if directory given
    assert prange.webseed_url("https://example.com/data/") == ws_url
    assert prange.webseed_url("https://example.com/data") == ws_url


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_webseed_url_multifile(version: str, tmp_path: Path):
    """
    Multifile torrents should have their `info.name` prepended to the webseed url
    """
    t_name = "my_torrent"
    t_dir = tmp_path / t_name
    t_dir.mkdir(exist_ok=True)
    paths = [Path("a.exe"), Path("b.exe"), Path("c.png")]
    for path in paths:
        with open(t_dir / path, "wb") as f:
            f.write(random.randbytes((32 * KiB) * 4))

    t = TorrentCreate(paths=paths, path_root=t_dir, piece_length=32 * KiB).generate(version=version)
    assert t.info.name == t_name
    if version == "v1":
        v1_range = t.layout.v1_piece_range(6)
        prange = v1_range.ranges[0]
    else:
        prange = t.layout.v2_piece_range("b.exe", 2)

    ws_expected = "https://example.com/data/my_torrent/b.exe"
    # direct paths are unchanged
    assert prange.webseed_url(ws_expected) == ws_expected
    # ensure name is prepended to directories
    assert prange.webseed_url("https://example.com/data/") == ws_expected
    assert prange.webseed_url("https://example.com/data") == ws_expected


def test_print_hash():
    """
    When serialized in `print` mode, hashes should be serialized as strings everywhere
    """
    t = Torrent.read(DATA_DIR / "qbt_directory_hybrid.torrent")
    dumped = t.model_dump(context={"mode": "print"})
    assert all([isinstance(p, str) for p in dumped["info"]["pieces"]])
    assert all(
        [isinstance(f[""]["pieces root"], str) for f in dumped["info"]["file_tree"].values()]
    )
    assert all([isinstance(k, str) for k in dumped["piece_layers"]])
    for k, v in dumped["piece_layers"].items():
        assert isinstance(k, str)
        assert all([isinstance(v_hash, str) for v_hash in v])


def test_safe_join(tmp_path: Path):
    assert safe_join(tmp_path, "a/b") == tmp_path.resolve() / "a" / "b"
    for path in ("../escape", "a/../../escape", "/etc/passwd"):
        with pytest.raises(ValueError):
            safe_join(tmp_path, path)
