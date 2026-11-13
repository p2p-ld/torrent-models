import random
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from torrent_models import KiB, Torrent, TorrentCreate, TorrentVersion

__all__ = [
    "EXPECTED_PIECES",
    "LAYOUTS",
    "ExpectedPieces",
    "LayoutFiles",
    "expected_pieces",
    "file_layout",
    "layout_torrent",
]


@dataclass
class LayoutFiles:
    """A set of files to make torrents from"""

    name: str
    files: dict[str, int]
    """path: size"""
    versions: tuple[TorrentVersion, ...] = tuple(TorrentVersion)
    """Torrent versions that can be made from these files"""
    piece_length: int = 32 * KiB
    path: Path | None = None
    """Directory containing the files, once they are written"""


LAYOUTS = [
    LayoutFiles("single", {"a": 100 * KiB}),
    LayoutFiles("single_small", {"a": 10 * KiB}),
    LayoutFiles("aligned", {"a": 32 * KiB, "b": 64 * KiB, "c": 32 * KiB}),
    LayoutFiles("smaller_than_piece", {"a": 5 * KiB, "b": 10 * KiB, "c": 8 * KiB, "d": 3 * KiB}),
    LayoutFiles("straddling", {"a": 20 * KiB, "b": 44 * KiB, "c": 40 * KiB, "d": 50 * KiB}),
    LayoutFiles("odd_size", {"a": 10 * KiB, "b": 100 * KiB + 7, "c": 10 * KiB}),
    LayoutFiles("nested", {"a/x": 20 * KiB, "b": 40 * KiB, "c/d/e": 10 * KiB}),
    # TorrentCreate leaves empty files out of v2 file trees
    LayoutFiles(
        "empty_file", {"a": 40 * KiB, "b": 0, "c": 50 * KiB}, versions=(TorrentVersion.v1,)
    ),
]


@pytest.fixture(scope="session", params=LAYOUTS, ids=lambda layout: layout.name)
def file_layout(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> LayoutFiles:
    """One of the :data:`LAYOUTS`, with its files written to disk"""
    layout: LayoutFiles = request.param
    path = tmp_path_factory.mktemp(layout.name)
    for file, size in layout.files.items():
        (path / file).parent.mkdir(parents=True, exist_ok=True)
        (path / file).write_bytes(random.randbytes(size))
    return LayoutFiles(
        name=layout.name,
        files=layout.files,
        versions=layout.versions,
        piece_length=layout.piece_length,
        path=path,
    )


@pytest.fixture(scope="session", params=list(TorrentVersion))
def layout_torrent(request: pytest.FixtureRequest, file_layout: LayoutFiles) -> Torrent:
    """
    A torrent made from a :func:`file_layout`.
    Indirectly parametrize with the versions a test needs, if not all of them.

    Shared across the test session, so don't modify it.
    """
    version: TorrentVersion = request.param
    if version not in file_layout.versions:
        pytest.skip(f"Can't make a {version} torrent from the {file_layout.name} layout")
    assert file_layout.path is not None
    paths = [file_layout.path / file for file in file_layout.files]
    create = TorrentCreate(
        paths=paths, path_root=file_layout.path, piece_length=file_layout.piece_length
    )
    return create.generate(version)


@dataclass
class ExpectedPieces:
    """
    Piece ranges we expect for some of the files and pieces in a layout torrent.

    v1 torrents lay files end to end, top-level files first.
    v2 torrents start each file on a new piece, numbering pieces across the whole torrent
    in file tree order.
    Hybrid torrents use the v2 file order, and pad each file to a piece boundary,
    so their v1 and v2 piece indices are the same.
    """

    n_pieces: int | None = None
    """Number of pieces in the torrent"""
    v1_file_pieces: dict[str, list[int]] = field(default_factory=dict)
    """file path: indices of the v1 pieces that contain the file"""
    v2_file_pieces: dict[str, list[tuple[int, int, int, int]]] = field(default_factory=dict)
    """file path: (piece_idx, file_piece_idx, range_start, range_end) of each of its v2 pieces"""
    v1_pieces: dict[int, list[tuple[str, int, int]]] = field(default_factory=dict)
    """piece index: (file path, range_start, range_end) of each file in the v1 piece"""
    v2_pieces: dict[int, tuple[str, int, int, int]] = field(default_factory=dict)
    """piece index: (file path, file_piece_idx, range_start, range_end) of the v2 piece"""
    v1_byte_range_pieces: dict[tuple[str, int, int], list[int]] = field(default_factory=dict)
    """(file path, start, end): indices of the v1 pieces that contain that byte range of the file"""
    v2_byte_range_pieces: dict[tuple[str, int, int], list[int]] = field(default_factory=dict)
    """(file path, start, end): indices of the v2 pieces that contain that byte range of the file"""


EXPECTED_PIECES: dict[str, dict[TorrentVersion, ExpectedPieces]] = {
    "single": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"a": [0, 1, 2, 3]},
            v1_pieces={3: [("a", 96 * KiB, 100 * KiB)]},
            v1_byte_range_pieces={
                # end is exclusive, so ending on a piece boundary doesn't include the next piece
                ("a", 0, 32 * KiB): [0],
                ("a", 32 * KiB - 1, 32 * KiB + 1): [0, 1],
                ("a", 99 * KiB, 100 * KiB): [3],
            },
        ),
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=4,
            v2_file_pieces={
                "a": [
                    (0, 0, 0, 32 * KiB),
                    (1, 1, 32 * KiB, 64 * KiB),
                    (2, 2, 64 * KiB, 96 * KiB),
                    (3, 3, 96 * KiB, 100 * KiB),
                ]
            },
            v2_pieces={3: ("a", 3, 96 * KiB, 100 * KiB)},
            v2_byte_range_pieces={
                ("a", 0, 32 * KiB): [0],
                ("a", 32 * KiB - 1, 32 * KiB + 1): [0, 1],
                ("a", 99 * KiB, 100 * KiB): [3],
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"a": [0, 1, 2, 3]},
            v2_file_pieces={
                "a": [
                    (0, 0, 0, 32 * KiB),
                    (1, 1, 32 * KiB, 64 * KiB),
                    (2, 2, 64 * KiB, 96 * KiB),
                    (3, 3, 96 * KiB, 100 * KiB),
                ]
            },
            v1_pieces={3: [("a", 96 * KiB, 100 * KiB), (".pad/28672", 0, 28 * KiB)]},
            v2_pieces={3: ("a", 3, 96 * KiB, 100 * KiB)},
            v1_byte_range_pieces={
                ("a", 0, 32 * KiB): [0],
                ("a", 32 * KiB - 1, 32 * KiB + 1): [0, 1],
                ("a", 99 * KiB, 100 * KiB): [3],
            },
            v2_byte_range_pieces={
                ("a", 0, 32 * KiB): [0],
                ("a", 32 * KiB - 1, 32 * KiB + 1): [0, 1],
                ("a", 99 * KiB, 100 * KiB): [3],
            },
        ),
    },
    "single_small": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=1,
            v1_file_pieces={"a": [0]},
            v1_pieces={0: [("a", 0, 10 * KiB)]},
            v1_byte_range_pieces={("a", 5 * KiB, 5 * KiB): [], ("a", 9 * KiB, 10 * KiB): [0]},
        ),
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=1,
            v2_file_pieces={"a": [(0, 0, 0, 10 * KiB)]},
            v2_pieces={0: ("a", 0, 0, 10 * KiB)},
            v2_byte_range_pieces={("a", 5 * KiB, 5 * KiB): [], ("a", 9 * KiB, 10 * KiB): [0]},
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=1,
            v1_file_pieces={"a": [0]},
            v2_file_pieces={"a": [(0, 0, 0, 10 * KiB)]},
            v1_pieces={0: [("a", 0, 10 * KiB), (".pad/22528", 0, 22 * KiB)]},
            v2_pieces={0: ("a", 0, 0, 10 * KiB)},
            v1_byte_range_pieces={("a", 5 * KiB, 5 * KiB): [], ("a", 9 * KiB, 10 * KiB): [0]},
            v2_byte_range_pieces={("a", 5 * KiB, 5 * KiB): [], ("a", 9 * KiB, 10 * KiB): [0]},
        ),
    },
    "aligned": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"b": [1, 2]},
            v1_pieces={1: [("b", 0, 32 * KiB)]},
            v1_byte_range_pieces={("b", 0, 1): [1], ("b", 32 * KiB, 64 * KiB): [2]},
        ),
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=4,
            v2_file_pieces={
                "a": [(0, 0, 0, 32 * KiB)],
                "b": [(1, 0, 0, 32 * KiB), (2, 1, 32 * KiB, 64 * KiB)],
            },
            v2_pieces={2: ("b", 1, 32 * KiB, 64 * KiB), 3: ("c", 0, 0, 32 * KiB)},
            v2_byte_range_pieces={("b", 0, 1): [1], ("b", 32 * KiB, 64 * KiB): [2]},
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"b": [(1, 0, 0, 32 * KiB), (2, 1, 32 * KiB, 64 * KiB)]},
            v1_pieces={1: [("b", 0, 32 * KiB)]},
            v2_pieces={2: ("b", 1, 32 * KiB, 64 * KiB), 3: ("c", 0, 0, 32 * KiB)},
            v1_byte_range_pieces={("b", 0, 1): [1], ("b", 32 * KiB, 64 * KiB): [2]},
            v2_byte_range_pieces={("b", 0, 1): [1], ("b", 32 * KiB, 64 * KiB): [2]},
        ),
    },
    "smaller_than_piece": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=1,
            v1_file_pieces={"c": [0]},
            v1_pieces={
                0: [("a", 0, 5 * KiB), ("b", 0, 10 * KiB), ("c", 0, 8 * KiB), ("d", 0, 3 * KiB)]
            },
            v1_byte_range_pieces={("c", 7 * KiB, 8 * KiB): [0], ("d", 2 * KiB, 3 * KiB): [0]},
        ),
        # each file gets a whole piece to itself
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=4,
            v2_file_pieces={"c": [(2, 0, 0, 8 * KiB)]},
            v2_pieces={0: ("a", 0, 0, 5 * KiB), 3: ("d", 0, 0, 3 * KiB)},
            v2_byte_range_pieces={("c", 7 * KiB, 8 * KiB): [2]},
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"c": [2]},
            v2_file_pieces={"c": [(2, 0, 0, 8 * KiB)]},
            v1_pieces={0: [("a", 0, 5 * KiB), (".pad/27648", 0, 27 * KiB)]},
            v2_pieces={0: ("a", 0, 0, 5 * KiB), 3: ("d", 0, 0, 3 * KiB)},
            v1_byte_range_pieces={("c", 7 * KiB, 8 * KiB): [2], ("d", 2 * KiB, 3 * KiB): [3]},
            v2_byte_range_pieces={("c", 7 * KiB, 8 * KiB): [2], ("d", 2 * KiB, 3 * KiB): [3]},
        ),
    },
    "straddling": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=5,
            v1_file_pieces={"b": [0, 1], "d": [3, 4]},
            v1_pieces={
                0: [("a", 0, 20 * KiB), ("b", 0, 12 * KiB)],
                1: [("b", 12 * KiB, 44 * KiB)],
                # starts exactly where c starts
                2: [("c", 0, 32 * KiB)],
                3: [("c", 32 * KiB, 40 * KiB), ("d", 0, 24 * KiB)],
            },
            # b starts 20 KiB into piece 0, so piece 1 starts 12 KiB into b
            v1_byte_range_pieces={
                ("b", 0, 12 * KiB): [0],
                ("b", 12 * KiB - 1, 12 * KiB + 1): [0, 1],
                ("b", 12 * KiB, 44 * KiB): [1],
                ("d", 0, 1): [3],
                ("d", 24 * KiB, 50 * KiB): [4],
            },
        ),
        # a is piece 0, b is 1-2, c is 3-4, d is 5-6
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=7,
            v2_file_pieces={"d": [(5, 0, 0, 32 * KiB), (6, 1, 32 * KiB, 50 * KiB)]},
            v2_pieces={
                1: ("b", 0, 0, 32 * KiB),
                2: ("b", 1, 32 * KiB, 44 * KiB),
                5: ("d", 0, 0, 32 * KiB),
            },
            v2_byte_range_pieces={
                ("d", 0, 1): [5],
                ("d", 24 * KiB, 50 * KiB): [5, 6],
                ("d", 32 * KiB, 50 * KiB): [6],
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=7,
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"d": [(5, 0, 0, 32 * KiB), (6, 1, 32 * KiB, 50 * KiB)]},
            v1_pieces={2: [("b", 32 * KiB, 44 * KiB), (".pad/20480", 0, 20 * KiB)]},
            v2_pieces={
                1: ("b", 0, 0, 32 * KiB),
                2: ("b", 1, 32 * KiB, 44 * KiB),
                5: ("d", 0, 0, 32 * KiB),
            },
            # padfiles before each file move it to the start of a piece
            v1_byte_range_pieces={
                ("b", 0, 1): [1],
                ("b", 32 * KiB, 44 * KiB): [2],
                ("d", 24 * KiB, 50 * KiB): [5, 6],
            },
            v2_byte_range_pieces={
                ("b", 0, 1): [1],
                ("b", 32 * KiB, 44 * KiB): [2],
                ("d", 24 * KiB, 50 * KiB): [5, 6],
            },
        ),
    },
    "odd_size": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"b": [0, 1, 2, 3]},
            v1_pieces={3: [("b", 86 * KiB, 100 * KiB + 7), ("c", 0, 10 * KiB)]},
            v1_byte_range_pieces={
                ("b", 22 * KiB - 1, 22 * KiB + 1): [0, 1],
                ("b", 100 * KiB + 6, 100 * KiB + 7): [3],
            },
        ),
        # a is piece 0, b is 1-4, c is 5
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=6,
            v2_file_pieces={
                "b": [
                    (1, 0, 0, 32 * KiB),
                    (2, 1, 32 * KiB, 64 * KiB),
                    (3, 2, 64 * KiB, 96 * KiB),
                    (4, 3, 96 * KiB, 100 * KiB + 7),
                ]
            },
            v2_pieces={4: ("b", 3, 96 * KiB, 100 * KiB + 7), 5: ("c", 0, 0, 10 * KiB)},
            v2_byte_range_pieces={
                ("b", 22 * KiB - 1, 22 * KiB + 1): [1],
                ("b", 100 * KiB + 6, 100 * KiB + 7): [4],
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=6,
            v1_file_pieces={"b": [1, 2, 3, 4]},
            v2_file_pieces={
                "b": [
                    (1, 0, 0, 32 * KiB),
                    (2, 1, 32 * KiB, 64 * KiB),
                    (3, 2, 64 * KiB, 96 * KiB),
                    (4, 3, 96 * KiB, 100 * KiB + 7),
                ]
            },
            v1_pieces={4: [("b", 96 * KiB, 100 * KiB + 7), (".pad/28665", 0, 28 * KiB - 7)]},
            v2_pieces={4: ("b", 3, 96 * KiB, 100 * KiB + 7), 5: ("c", 0, 0, 10 * KiB)},
            v1_byte_range_pieces={
                ("b", 22 * KiB - 1, 22 * KiB + 1): [1],
                ("b", 100 * KiB + 6, 100 * KiB + 7): [4],
            },
            v2_byte_range_pieces={
                ("b", 22 * KiB - 1, 22 * KiB + 1): [1],
                ("b", 100 * KiB + 6, 100 * KiB + 7): [4],
            },
        ),
    },
    # v1 puts the top-level file b first, v2 and hybrid sort a/x first:
    # a/x is piece 0, b is 1-2, c/d/e is 3
    "nested": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=3,
            v1_file_pieces={"a/x": [1], "c/d/e": [1, 2]},
            v1_pieces={1: [("b", 32 * KiB, 40 * KiB), ("a/x", 0, 20 * KiB), ("c/d/e", 0, 4 * KiB)]},
            v1_byte_range_pieces={
                ("a/x", 0, 20 * KiB): [1],
                ("c/d/e", 0, 4 * KiB): [1],
                ("c/d/e", 4 * KiB, 10 * KiB): [2],
            },
        ),
        TorrentVersion.v2: ExpectedPieces(
            n_pieces=4,
            v2_file_pieces={"c/d/e": [(3, 0, 0, 10 * KiB)]},
            v2_pieces={0: ("a/x", 0, 0, 20 * KiB), 2: ("b", 1, 32 * KiB, 40 * KiB)},
            v2_byte_range_pieces={("c/d/e", 4 * KiB, 10 * KiB): [3]},
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            n_pieces=4,
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"c/d/e": [(3, 0, 0, 10 * KiB)]},
            v1_pieces={0: [("a/x", 0, 20 * KiB), (".pad/12288", 0, 12 * KiB)]},
            v2_pieces={0: ("a/x", 0, 0, 20 * KiB), 2: ("b", 1, 32 * KiB, 40 * KiB)},
            v1_byte_range_pieces={
                ("a/x", 0, 20 * KiB): [0],
                ("b", 0, 1): [1],
                ("c/d/e", 4 * KiB, 10 * KiB): [3],
            },
            v2_byte_range_pieces={
                ("a/x", 0, 20 * KiB): [0],
                ("b", 0, 1): [1],
                ("c/d/e", 4 * KiB, 10 * KiB): [3],
            },
        ),
    },
    "empty_file": {
        TorrentVersion.v1: ExpectedPieces(
            n_pieces=3,
            v1_file_pieces={"b": [], "c": [1, 2]},
            # empty files within a piece get a zero-length range
            v1_pieces={1: [("a", 32 * KiB, 40 * KiB), ("b", 0, 0), ("c", 0, 24 * KiB)]},
            v1_byte_range_pieces={
                ("b", 0, 0): [],
                ("c", 0, 1): [1],
                ("c", 24 * KiB - 1, 24 * KiB + 1): [1, 2],
            },
        ),
    },
}
"""layout name: torrent version: expected pieces"""


@pytest.fixture(scope="session")
def expected_pieces(file_layout: LayoutFiles, layout_torrent: Torrent) -> ExpectedPieces:
    """
    The :data:`EXPECTED_PIECES` for a :func:`layout_torrent`.

    Raises if they are missing any of the expected pieces for the torrent's version.
    """
    version = layout_torrent.torrent_version
    case = f"{version} torrents of the {file_layout.name} layout"
    try:
        expected = EXPECTED_PIECES[file_layout.name][version]
    except KeyError as e:
        raise ValueError(f"No expected pieces for {case}") from e

    if expected.n_pieces is None:
        raise ValueError(f"Missing expected number of pieces for {case}")
    if version in (TorrentVersion.v1, TorrentVersion.hybrid) and not (
        expected.v1_file_pieces and expected.v1_pieces and expected.v1_byte_range_pieces
    ):
        raise ValueError(
            f"Missing expected v1 file pieces, v1 pieces, or v1 byte range pieces for {case}"
        )
    if version in (TorrentVersion.v2, TorrentVersion.hybrid) and not (
        expected.v2_file_pieces and expected.v2_pieces and expected.v2_byte_range_pieces
    ):
        raise ValueError(
            f"Missing expected v2 file pieces, v2 pieces, or v2 byte range pieces for {case}"
        )
    return expected
