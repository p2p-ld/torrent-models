import posixpath
import random
import string
from math import ceil
from pathlib import Path

import pytest

from torrent_models import KiB, TorrentCreate, TorrentVersion
from torrent_models.const import EXCLUDE_FILES
from torrent_models.hashing.v1 import sort_v1

SIZES = [10 * KiB, 20 * KiB, 32 * KiB, 40 * KiB, 100 * KiB]


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
        range = torrent.v1_piece_range(i)
        assert range.piece_hash == piece
        data = []
        for file in range.ranges:
            if file.is_padfile:
                data.append(bytes(file.range_end - file.range_start))
            else:
                path = posixpath.join(*file.path)
                seen_files.add(path)
                with open(tmp_path / path, "rb") as f:
                    f.seek(file.range_start)
                    data.append(f.read(file.range_end - file.range_start))

        assert range.validate_data(data)

        # we reject random data in the right shape
        fake_data = [random.randbytes(len(d)) for d in data]
        assert not range.validate_data(fake_data)

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
            piece_range = torrent.v2_piece_range(path, piece_idx)
            assert piece_range.range_start == piece_idx * 32 * KiB

            with open(tmp_path / path, "rb") as f:
                f.seek(piece_range.range_start)
                data = f.read(piece_range.range_end - piece_range.range_start)
            data = [data[i : i + (16 * KiB)] for i in range(0, len(data), 16 * KiB)]
            assert piece_range.validate_data(data)

            # reject random data in the right shape
            data = [random.randbytes(len(d)) for d in data]
            assert not piece_range.validate_data(data)


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
        left_piece = torrent.v1_piece_range(left)
        right_piece = torrent.v1_piece_range(right)
        if left_piece.ranges[-1].path == right_piece.ranges[0].path:
            assert left_piece.ranges[-1].range_end == right_piece.ranges[0].range_start
        else:
            assert left_piece.ranges[-1].range_end == left_piece.ranges[-1].length
            assert right_piece.ranges[0].range_start == 0
