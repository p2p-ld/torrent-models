import posixpath
import random
import string
from math import ceil
from pathlib import Path

import pytest

from torrent_models import KiB, TorrentCreate, TorrentVersion
from torrent_models.const import EXCLUDE_FILES

SIZES = [10 * KiB, 20 * KiB, 32 * KiB, 40 * KiB, 100 * KiB]


@pytest.fixture(params=SIZES)
def file_size(request: pytest.FixtureRequest, tmp_path: Path) -> int:
    """Create a set of files that are smaller than, equal to, and larger than a 32 KiB piece size"""

    size = request.param
    for name in string.ascii_letters[0:10]:
        with open(tmp_path / name, "wb") as f:
            f.write(random.randbytes(size))
    return size


@pytest.mark.parametrize("version", [TorrentVersion.v1, TorrentVersion.hybrid])
def test_v1_piece_range(file_size: int, version: TorrentVersion, tmp_path: Path):
    """
    We can get piece ranges from v1 torrents and validate data against them
    """
    files = [p for p in tmp_path.iterdir() if p.name not in EXCLUDE_FILES]
    assert len(files) == 10
    assert all([(tmp_path / p).stat().st_size == file_size for p in files])

    create = TorrentCreate(paths=files, path_root=tmp_path, piece_length=32 * KiB)
    torrent = create.generate(version=version)
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

    assert seen_files == {letter for letter in string.ascii_letters[0:10]}


@pytest.mark.parametrize("version", [TorrentVersion.v2, TorrentVersion.hybrid])
def test_v2_piece_range(file_size: int, version: TorrentVersion, tmp_path: Path):
    """
    We can get piece ranges from v2 torrents and validate data against them
    """
    files = [p for p in tmp_path.iterdir() if p.name not in EXCLUDE_FILES]
    assert len(files) == 10
    assert all([(tmp_path / p).stat().st_size == file_size for p in files])

    create = TorrentCreate(paths=files, path_root=tmp_path, piece_length=32 * KiB)
    torrent = create.generate(version=version)
    assert set(torrent.flat_files.keys()) == {letter for letter in string.ascii_letters[0:10]}
    for path, file_info in torrent.flat_files.items():
        root = file_info["pieces root"]
        n_pieces = 1 if root not in torrent.piece_layers else len(torrent.piece_layers[root])
        assert n_pieces == ceil(file_size / (32 * KiB))
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
