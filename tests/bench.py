import shutil
from pathlib import Path

import pytest
from torf import Torrent as TorfTorrent

from torrent_models import Torrent, TorrentCreate, TorrentVersion, size

DATA_DIR = (Path(__file__).parent / "data").resolve()

MULTI_HYBRID = DATA_DIR / "qbt_directory_hybrid.torrent"
MULTI_V1 = DATA_DIR / "qbt_directory_v1.torrent"
MULTI_V2 = DATA_DIR / "qbt_directory_v2.torrent"
GIANT_HYBRID = DATA_DIR / "qbt_giant_hybrid.torrent"
GIANT_V1 = DATA_DIR / "qbt_giant_v1.torrent"
GIANT_V2 = DATA_DIR / "qbt_giant_v2.torrent"

MULTI_FILE_HYBRID = Path(__file__).joinpath("../data/qbt_directory_hybrid.torrent").resolve()
GIANT_TORRENT = Path(__file__).joinpath("../data/qbt_giant_v1.torrent").resolve()


@pytest.fixture(
    params=[
        pytest.param(MULTI_HYBRID, id="multi-hybrid"),
        pytest.param(MULTI_V1, id="multi-v1"),
        pytest.param(MULTI_V2, id="multi-v2"),
        pytest.param(GIANT_HYBRID, id="giant-hybrid"),
        pytest.param(GIANT_V1, id="giant-v1"),
        pytest.param(GIANT_V2, id="giant-v2"),
    ]
)
def torrent_file(request) -> Path:
    if not request.param.exists():
        pytest.skip()
    return request.param


@pytest.fixture(
    params=[
        pytest.param(TorrentVersion.v1, id="v1"),
        pytest.param(TorrentVersion.v2, id="v2"),
        pytest.param(TorrentVersion.hybrid, id="hybrid"),
    ]
)
def torrent_version(request) -> TorrentVersion:
    return request.param


def _equal_sizes(path: Path, n: int, total_size: int) -> None:
    each_size = total_size // n
    for i in range(n):
        with open(path / f"{i}.bin", "wb") as f:
            f.write(bytes(each_size))


@pytest.fixture(
    scope="module",
    params=[
        pytest.param((1, 16 * size.KiB), id="files-1-size-16KiB"),
        pytest.param((1, 1 * size.GiB), id="files-1-size-1GiB"),
        pytest.param((5000, 16 * size.KiB), id="files-5000-size-64KiB"),
        pytest.param((5000, 1 * size.GiB), id="files-5000-size-1GiB"),
    ],
)
def torrent_equal_sizes(request, tmp_path_factory) -> tuple[Path, int, int]:
    n, size = request.param

    pth = tmp_path_factory.mktemp(f"{n}_{size}_equal")
    _equal_sizes(pth, n, size)
    yield pth, n, size
    shutil.rmtree(str(pth))


@pytest.fixture(
    params=[
        pytest.param(1 * size.MiB, id="piece-size-1MiB"),
        pytest.param(32 * size.MiB, id="piece-size-32MiB"),
    ]
)
def piece_size(request) -> int:
    return request.param


def test_benchmark_decode(benchmark, torrent_file):
    benchmark(Torrent.read, torrent_file)


def test_benchmark_decode_torf(benchmark, torrent_file, monkeypatch):
    monkeypatch.setattr(TorfTorrent, "MAX_TORRENT_FILE_SIZE", 100 * (2**20))
    if "v2" in str(torrent_file):
        pytest.xfail()
    benchmark(TorfTorrent.read, torrent_file)


def test_create(torrent_version, torrent_equal_sizes, piece_size, benchmark):
    path, n_files, total_size = torrent_equal_sizes
    if n_files > 1000 and piece_size >= (2 * size.MiB) and torrent_version == TorrentVersion.hybrid:
        pytest.skip("takes too long")

    def _hash_and_bencode() -> None:
        created = TorrentCreate(
            path_root=path,
            piece_length=piece_size,
            trackers=["https://example.com/announce"],
        ).generate(version=torrent_version)
        _ = created.bencode()

    benchmark(_hash_and_bencode)
