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
    Hybrid torrents use the v2 file order, and pad each file to a piece boundary.
    """

    v1_file_pieces: dict[str, list[int]] = field(default_factory=dict)
    """file path: indices of the v1 pieces that contain the file"""
    v2_file_pieces: dict[str, list[tuple[int, int, int]]] = field(default_factory=dict)
    """file path: (piece_idx, range_start, range_end) of each of the file's v2 pieces"""
    v1_pieces: dict[int, list[tuple[str, int, int]]] = field(default_factory=dict)
    """piece index: (file path, range_start, range_end) of each file in the v1 piece"""


EXPECTED_PIECES: dict[str, dict[TorrentVersion, ExpectedPieces]] = {
    "single": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"a": [0, 1, 2, 3]},
            v1_pieces={3: [("a", 96 * KiB, 100 * KiB)]},
        ),
        TorrentVersion.v2: ExpectedPieces(
            v2_file_pieces={
                "a": [
                    (0, 0, 32 * KiB),
                    (1, 32 * KiB, 64 * KiB),
                    (2, 64 * KiB, 96 * KiB),
                    (3, 96 * KiB, 100 * KiB),
                ]
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"a": [0, 1, 2, 3]},
            v2_file_pieces={
                "a": [
                    (0, 0, 32 * KiB),
                    (1, 32 * KiB, 64 * KiB),
                    (2, 64 * KiB, 96 * KiB),
                    (3, 96 * KiB, 100 * KiB),
                ]
            },
            v1_pieces={3: [("a", 96 * KiB, 100 * KiB), (".pad/28672", 0, 28 * KiB)]},
        ),
    },
    "single_small": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"a": [0]},
            v1_pieces={0: [("a", 0, 10 * KiB)]},
        ),
        TorrentVersion.v2: ExpectedPieces(v2_file_pieces={"a": [(0, 0, 10 * KiB)]}),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"a": [0]},
            v2_file_pieces={"a": [(0, 0, 10 * KiB)]},
            v1_pieces={0: [("a", 0, 10 * KiB), (".pad/22528", 0, 22 * KiB)]},
        ),
    },
    "aligned": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"b": [1, 2]},
            v1_pieces={1: [("b", 0, 32 * KiB)]},
        ),
        TorrentVersion.v2: ExpectedPieces(
            v2_file_pieces={
                "a": [(0, 0, 32 * KiB)],
                "b": [(0, 0, 32 * KiB), (1, 32 * KiB, 64 * KiB)],
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"b": [(0, 0, 32 * KiB), (1, 32 * KiB, 64 * KiB)]},
            v1_pieces={1: [("b", 0, 32 * KiB)]},
        ),
    },
    "smaller_than_piece": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"c": [0]},
            v1_pieces={
                0: [("a", 0, 5 * KiB), ("b", 0, 10 * KiB), ("c", 0, 8 * KiB), ("d", 0, 3 * KiB)]
            },
        ),
        TorrentVersion.v2: ExpectedPieces(v2_file_pieces={"c": [(0, 0, 8 * KiB)]}),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"c": [2]},
            v2_file_pieces={"c": [(0, 0, 8 * KiB)]},
            v1_pieces={0: [("a", 0, 5 * KiB), (".pad/27648", 0, 27 * KiB)]},
        ),
    },
    "straddling": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"b": [0, 1], "d": [3, 4]},
            v1_pieces={
                0: [("a", 0, 20 * KiB), ("b", 0, 12 * KiB)],
                1: [("b", 12 * KiB, 44 * KiB)],
                # starts exactly where c starts
                2: [("c", 0, 32 * KiB)],
                3: [("c", 32 * KiB, 40 * KiB), ("d", 0, 24 * KiB)],
            },
        ),
        TorrentVersion.v2: ExpectedPieces(
            v2_file_pieces={"d": [(0, 0, 32 * KiB), (1, 32 * KiB, 50 * KiB)]}
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"d": [(0, 0, 32 * KiB), (1, 32 * KiB, 50 * KiB)]},
            v1_pieces={2: [("b", 32 * KiB, 44 * KiB), (".pad/20480", 0, 20 * KiB)]},
        ),
    },
    "odd_size": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"b": [0, 1, 2, 3]},
            v1_pieces={3: [("b", 86 * KiB, 100 * KiB + 7), ("c", 0, 10 * KiB)]},
        ),
        TorrentVersion.v2: ExpectedPieces(
            v2_file_pieces={
                "b": [
                    (0, 0, 32 * KiB),
                    (1, 32 * KiB, 64 * KiB),
                    (2, 64 * KiB, 96 * KiB),
                    (3, 96 * KiB, 100 * KiB + 7),
                ]
            },
        ),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"b": [1, 2, 3, 4]},
            v2_file_pieces={
                "b": [
                    (0, 0, 32 * KiB),
                    (1, 32 * KiB, 64 * KiB),
                    (2, 64 * KiB, 96 * KiB),
                    (3, 96 * KiB, 100 * KiB + 7),
                ]
            },
            v1_pieces={4: [("b", 96 * KiB, 100 * KiB + 7), (".pad/28665", 0, 28 * KiB - 7)]},
        ),
    },
    # v1 puts the top-level file b first, v2 and hybrid sort a/x first
    "nested": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"a/x": [1], "c/d/e": [1, 2]},
            v1_pieces={1: [("b", 32 * KiB, 40 * KiB), ("a/x", 0, 20 * KiB), ("c/d/e", 0, 4 * KiB)]},
        ),
        TorrentVersion.v2: ExpectedPieces(v2_file_pieces={"c/d/e": [(0, 0, 10 * KiB)]}),
        TorrentVersion.hybrid: ExpectedPieces(
            v1_file_pieces={"b": [1, 2]},
            v2_file_pieces={"c/d/e": [(0, 0, 10 * KiB)]},
            v1_pieces={0: [("a/x", 0, 20 * KiB), (".pad/12288", 0, 12 * KiB)]},
        ),
    },
    "empty_file": {
        TorrentVersion.v1: ExpectedPieces(
            v1_file_pieces={"b": [], "c": [1, 2]},
            # empty files within a piece get a zero-length range
            v1_pieces={1: [("a", 32 * KiB, 40 * KiB), ("b", 0, 0), ("c", 0, 24 * KiB)]},
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

    if version in (TorrentVersion.v1, TorrentVersion.hybrid) and not (
        expected.v1_file_pieces and expected.v1_pieces
    ):
        raise ValueError(f"Missing expected v1 file pieces or v1 pieces for {case}")
    if version in (TorrentVersion.v2, TorrentVersion.hybrid) and not expected.v2_file_pieces:
        raise ValueError(f"Missing expected v2 file pieces for {case}")
    return expected
