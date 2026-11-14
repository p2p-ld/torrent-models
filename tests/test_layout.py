import posixpath
import random
import string
from math import ceil
from pathlib import Path

import pytest

from torrent_models import BLOCK_SIZE, KiB, Torrent, TorrentCreate, TorrentVersion
from torrent_models.const import EXCLUDE_FILES
from torrent_models.hashing.v1 import sort_v1
from torrent_models.types.v1 import V1PieceRange
from torrent_models.types.v2 import V2PieceRange

from .conftest import DATA_DIR
from .fixtures import ExpectedPieces

SIZES = [10 * KiB, 20 * KiB, 32 * KiB, 40 * KiB, 100 * KiB]
CLIENT_TORRENTS = sorted(DATA_DIR.glob("*_basic_*.torrent"))
V1_VERSIONS = [TorrentVersion.v1, TorrentVersion.hybrid]
V2_VERSIONS = [TorrentVersion.v2, TorrentVersion.hybrid]


@pytest.fixture(params=[*SIZES, "multi"])
def random_data(tmp_path: Path, request: pytest.FixtureRequest) -> list[int]:
    """
    Create a set of files that are smaller than, equal to, and larger than a 32 KiB piece size

    handle the case of all the same size (e.g. to test cases with repeated piece alignment vs not,)
    as well as random samples of all sizes
    """

    sizes = []
    for _ in range(10):
        if request.param == "multi":
            sizes.extend(list(random.sample(SIZES, k=len(SIZES))))
        else:
            sizes.extend([request.param] * len(SIZES))
    for i, size in enumerate(sizes):
        with open(tmp_path / (string.ascii_letters[i] + str(i)), "wb") as f:
            f.write(random.randbytes(size))
    return sizes


@pytest.mark.parametrize("version", [TorrentVersion.v1, TorrentVersion.hybrid])
def test_v1_piece_range(random_data: list[int], version: TorrentVersion, tmp_path: Path):
    """
    We can get piece ranges from v1 torrents and validate data against them
    """
    files = [p for p in tmp_path.iterdir() if p.name not in EXCLUDE_FILES]

    create = TorrentCreate(paths=files, path_root=tmp_path, piece_length=32 * KiB)
    torrent = create.generate(version=version)
    assert len(random_data) == len(torrent.files)

    seen_files = set()
    for i, piece in enumerate(torrent.info.pieces):
        piece_range = torrent.layout.v1_piece_range(i)
        assert piece_range.piece_hash == piece
        data = []
        for file in piece_range.ranges:
            if file.is_padfile:
                data.append(bytes(file.range_end - file.range_start))
            else:
                path = posixpath.join(*file.path)
                seen_files.add(path)
                with open(tmp_path / path, "rb") as f:
                    f.seek(file.range_start)
                    data.append(f.read(file.range_end - file.range_start))

        assert piece_range.validate_data(data)
        # chunking doesn't matter, e.g. whole pieces, or 16 KiB blocks as peers send them
        joined = b"".join(data)
        assert len(joined) == piece_range.size
        assert piece_range.validate_data(joined)
        assert piece_range.validate_data(
            [joined[i : i + BLOCK_SIZE] for i in range(0, len(joined), BLOCK_SIZE)]
        )

        # we reject random data in the right shape
        fake_data = [random.randbytes(len(d)) for d in data]
        assert not piece_range.validate_data(fake_data)

    assert seen_files == {f.name for f in files}


@pytest.mark.parametrize("version", [TorrentVersion.v2, TorrentVersion.hybrid])
def test_v2_piece_range(random_data: list[int], version: TorrentVersion, tmp_path: Path):
    """
    We can get piece ranges from v2 torrents and validate data against them
    """
    files = [p for p in tmp_path.iterdir() if p.name not in EXCLUDE_FILES]

    create = TorrentCreate(paths=files, path_root=tmp_path, piece_length=32 * KiB)
    torrent = create.generate(version=version)
    assert len(random_data) == len(torrent.files)
    for path, file_info in torrent.flat_files.items():
        root = file_info["pieces root"]
        n_pieces = 1 if root not in torrent.piece_layers else len(torrent.piece_layers[root])
        assert n_pieces == ceil(file_info["length"] / (32 * KiB))
        for piece_idx in range(n_pieces):
            piece_range = torrent.layout.v2_piece_range(path, piece_idx)
            assert piece_range.range_start == piece_idx * 32 * KiB

            with open(tmp_path / path, "rb") as f:
                f.seek(piece_range.range_start)
                data = f.read(piece_range.range_end - piece_range.range_start)
            assert piece_range.validate_data(data)
            # chunking doesn't matter, e.g. 16 KiB blocks as peers send them
            assert piece_range.validate_data(
                [data[i : i + BLOCK_SIZE] for i in range(0, len(data), BLOCK_SIZE)]
            )
            assert piece_range.validate_data([data[:1], data[1:]])

            # reject random data in the right shape
            assert not piece_range.validate_data(random.randbytes(len(data)))


def test_v1_piece_ranges_sequential(random_data: list[int], tmp_path: Path):
    """
    Test that our piece ranges are what we expect from v1 files laid end to end,
    particularly no repeats.
    """
    files = sort_v1([p for p in tmp_path.iterdir() if p.name not in EXCLUDE_FILES])
    create = TorrentCreate(paths=files, path_root=tmp_path, piece_length=32 * KiB)
    torrent = create.generate(version="v1")
    assert len(random_data) == len(torrent.files)

    for left, right in zip(
        range(0, len(torrent.info.pieces) - 1), range(1, len(torrent.info.pieces))
    ):
        left_piece = torrent.layout.v1_piece_range(left)
        right_piece = torrent.layout.v1_piece_range(right)
        if left_piece.ranges[-1].path == right_piece.ranges[0].path:
            assert left_piece.ranges[-1].range_end == right_piece.ranges[0].range_start
        else:
            assert left_piece.ranges[-1].range_end == left_piece.ranges[-1].length
            assert right_piece.ranges[0].range_start == 0


@pytest.mark.parametrize("layout_torrent", V1_VERSIONS, indirect=True)
def test_v1_file_pieces(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """We get the v1 pieces that contain a file"""
    for path, expected in expected_pieces.v1_file_pieces.items():
        pieces = layout_torrent.layout.v1_file_pieces(path)
        assert [p.piece_idx for p in pieces] == expected, path


@pytest.mark.parametrize("layout_torrent", V2_VERSIONS, indirect=True)
def test_v2_file_pieces(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """
    We get the v2 pieces of a file, their indices within the torrent and the file,
    and their byte ranges within the file
    """
    for path, expected in expected_pieces.v2_file_pieces.items():
        pieces = layout_torrent.layout.v2_file_pieces(path)
        actual = [(p.piece_idx, p.file_piece_idx, p.range_start, p.range_end) for p in pieces]
        assert actual == expected, path


@pytest.mark.parametrize("layout_torrent", V2_VERSIONS, indirect=True)
def test_v2_piece_range_at(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """We get the file and byte range of a v2 piece from its index within the torrent"""
    for piece_idx, expected in expected_pieces.v2_pieces.items():
        piece = layout_torrent.layout.v2_piece_range_at(piece_idx)
        assert piece.piece_idx == piece_idx
        actual = (piece.path, piece.file_piece_idx, piece.range_start, piece.range_end)
        assert actual == expected, piece_idx


def test_n_pieces(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    assert layout_torrent.layout.n_pieces == expected_pieces.n_pieces


@pytest.mark.parametrize("layout_torrent", V1_VERSIONS, indirect=True)
def test_v1_piece_range_files(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """We get the files in a v1 piece, and the byte range of each"""
    for piece_idx, expected in expected_pieces.v1_pieces.items():
        piece = layout_torrent.layout.v1_piece_range(piece_idx)
        actual = [("/".join(r.path), r.range_start, r.range_end) for r in piece.ranges]
        assert actual == expected, piece_idx


@pytest.mark.parametrize("layout_torrent", V1_VERSIONS, indirect=True)
def test_v1_byte_range_pieces(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """We get the v1 pieces that contain a byte range of a file"""
    for (path, start, end), expected in expected_pieces.v1_byte_range_pieces.items():
        pieces = layout_torrent.layout.v1_byte_range_pieces(path, start, end)
        assert [p.piece_idx for p in pieces] == expected, (path, start, end)


@pytest.mark.parametrize("layout_torrent", V2_VERSIONS, indirect=True)
def test_v2_byte_range_pieces(layout_torrent: Torrent, expected_pieces: ExpectedPieces):
    """We get the v2 pieces that contain a byte range of a file"""
    for (path, start, end), expected in expected_pieces.v2_byte_range_pieces.items():
        pieces = layout_torrent.layout.v2_byte_range_pieces(path, start, end)
        assert [p.piece_idx for p in pieces] == expected, (path, start, end)


@pytest.mark.parametrize("version", list(TorrentVersion))
def test_byte_range_pieces_out_of_range(tmp_path: Path, version: TorrentVersion):
    torrent = _small_torrent(tmp_path, version)
    for start, end in [(-1, 10), (10, 5), (0, 40 * KiB + 1)]:
        with pytest.raises(IndexError):
            torrent.layout.byte_range_pieces("a", start, end)
    with pytest.raises(ValueError):
        torrent.layout.byte_range_pieces("not_a_file", 0, 1)


def _small_torrent(path: Path, version: TorrentVersion) -> Torrent:
    """A torrent with two 40 KiB files, `a` and `b`, in 32 KiB pieces"""
    for name in ("a", "b"):
        (path / name).write_bytes(random.randbytes(40 * KiB))
    return TorrentCreate(path_root=path, piece_length=32 * KiB).generate(version)


@pytest.mark.parametrize(
    "version,expected",
    [
        (TorrentVersion.v1, V1PieceRange),
        (TorrentVersion.v2, V2PieceRange),
        (TorrentVersion.hybrid, V2PieceRange),
    ],
)
def test_file_pieces_version(tmp_path: Path, version: TorrentVersion, expected: type):
    """
    file_pieces, byte_range_pieces, and piece_range give v1 ranges for v1 torrents,
    and prefer v2 ranges otherwise
    """
    torrent = _small_torrent(tmp_path, version)
    assert all(type(p) is expected for p in torrent.layout.file_pieces("a"))
    assert all(type(p) is expected for p in torrent.layout.byte_range_pieces("a", 0, 10))
    assert type(torrent.layout.piece_range(0)) is expected


def test_file_pieces_missing(tmp_path: Path):
    torrent = _small_torrent(tmp_path, TorrentVersion.hybrid)
    with pytest.raises(ValueError):
        torrent.layout.v1_file_pieces("not_a_file")
    with pytest.raises(ValueError):
        torrent.layout.v2_file_pieces("not_a_file")


def test_v1_piece_range_out_of_range(tmp_path: Path):
    torrent = _small_torrent(tmp_path, TorrentVersion.v1)
    with pytest.raises(IndexError):
        torrent.layout.v1_piece_range(len(torrent.info.pieces))


@pytest.mark.parametrize("version", V2_VERSIONS)
def test_v2_piece_range_out_of_range(tmp_path: Path, version: TorrentVersion):
    torrent = _small_torrent(tmp_path, version)
    # a and b are 2 pieces each
    for piece_idx in (-1, 4):
        with pytest.raises(IndexError):
            torrent.layout.v2_piece_range_at(piece_idx)
    for file_piece_idx in (-1, 2):
        with pytest.raises(IndexError):
            torrent.layout.v2_piece_range("a", file_piece_idx)


def test_deprecated_piece_range(tmp_path: Path):
    """The old piece range methods on Torrent warn and forward to the layout"""
    torrent = _small_torrent(tmp_path, TorrentVersion.hybrid)
    with pytest.warns(DeprecationWarning):
        assert torrent.v1_piece_range(0) == torrent.layout.v1_piece_range(0)
    with pytest.warns(DeprecationWarning):
        assert torrent.v2_piece_range("a") == torrent.layout.v2_piece_range("a")


@pytest.mark.parametrize("client", ["lt", "qbt"])
def test_v2_piece_index_clients(client: str):
    """
    In torrents made by libtorrent and qbittorrent, each v2 piece covers the same bytes
    as the hybrid torrent's v1 piece with the same index, which the client lined up with padfiles.
    That holds for the v2 pieces of both the hybrid and the v2-only torrent of the same files.
    """
    hybrid = Torrent.read(DATA_DIR / f"{client}_basic_hybrid.torrent")
    v2 = Torrent.read(DATA_DIR / f"{client}_basic_v2.torrent")
    assert hybrid.layout.n_pieces == v2.layout.n_pieces == len(hybrid.info.pieces)
    for piece_idx in range(len(hybrid.info.pieces)):
        v1_piece = hybrid.layout.v1_piece_range(piece_idx)
        v1_data = [
            ("/".join(r.path), r.range_start, r.range_end)
            for r in v1_piece.ranges
            if not r.is_padfile
        ]
        for torrent in (hybrid, v2):
            v2_piece = torrent.layout.v2_piece_range_at(piece_idx)
            assert v1_data == [(v2_piece.path, v2_piece.range_start, v2_piece.range_end)]


@pytest.mark.parametrize("tfile", [pytest.param(t, id=t.name) for t in CLIENT_TORRENTS])
def test_file_pieces_validate_clients(tfile: Path):
    """
    Data validates against the piece ranges of every file
    in torrents made by qbittorrent and libtorrent, with their own padfiles
    """
    torrent = Torrent.read(tfile)
    for file in torrent.files:
        for piece in torrent.layout.file_pieces(file.path):
            assert piece.validate_data(DATA_DIR)


@pytest.mark.parametrize("tfile", [pytest.param(t, id=t.name) for t in CLIENT_TORRENTS])
def test_file_by_path(tfile: Path):
    """Every file can be found by its path, in v1, v2 and hybrid torrents"""
    torrent = Torrent.read(tfile)
    for f in torrent.files:
        assert torrent.layout.file(f.path) is f
    with pytest.raises(ValueError):
        torrent.layout.file("not/in/the/torrent")


@pytest.mark.parametrize("tfile", [pytest.param(t, id=t.name) for t in CLIENT_TORRENTS])
def test_download_path_matches_piece_ranges(tfile: Path):
    """Files go where their piece ranges say, in v1, v2 and hybrid torrents"""
    torrent = Torrent.read(tfile)
    for f in torrent.files:
        for piece in torrent.layout.file_pieces(f.path):
            if isinstance(piece, V1PieceRange):
                paths = {r.full_path for r in piece.ranges if posixpath.join(*r.path) == f.path}
            else:
                paths = {piece.full_path}
            assert paths == {f.download_path}


@pytest.mark.parametrize("tfile", [pytest.param(t, id=t.name) for t in CLIENT_TORRENTS])
def test_check_clients(tfile: Path):
    """
    The data that torrents made by qbittorrent and libtorrent came from passes its check,
    and so do the v1 pieces of the hybrid ones, with their padfiles
    """
    torrent = Torrent.read(tfile)
    assert torrent.check(DATA_DIR)
    if torrent.torrent_version is TorrentVersion.hybrid:
        for piece_idx in range(torrent.layout.n_pieces):
            assert torrent.layout.v1_piece_range(piece_idx).validate_data(DATA_DIR)


@pytest.mark.parametrize("version", TorrentVersion)
def test_check_changed_or_missing(tmp_path: Path, version: TorrentVersion):
    """Data that's changed, cut short, or missing fails its check"""
    root = tmp_path / "t"
    root.mkdir()
    torrent = _small_torrent(root, version)
    assert torrent.check(tmp_path)
    b = root / "b"
    data = b.read_bytes()
    b.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])
    assert not torrent.check(tmp_path)
    b.write_bytes(data[:-1])
    assert not torrent.check(tmp_path)
    b.unlink()
    assert not torrent.check(tmp_path)


def test_check_refuses_paths_outside_root(tmp_path: Path):
    """A torrent whose paths lead out of the download directory can't read what's there"""
    files = [{"path": ["..", "..", "escape"], "length": 10}, {"path": ["b"], "length": 10}]
    info = {"name": "t", "piece length": 32 * KiB, "pieces": bytes(20), "files": files}
    torrent = Torrent.model_validate({"info": info})
    (tmp_path / "escape").write_bytes(bytes(10))
    root = tmp_path / "downloads"
    root.mkdir()
    with pytest.raises(ValueError):
        torrent.layout.piece_range(0).read(root)
    with pytest.raises(ValueError):
        torrent.check(root)
