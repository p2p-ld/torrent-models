import random
from pathlib import Path

import pytest

from torrent_models import KiB, Torrent, TorrentCreate

from .conftest import DATA_DIR


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
        v1_range = t.v1_piece_range(2)
        prange = v1_range.ranges[0]
    else:
        assert len(t.flat_files) == 1
        prange = t.v2_piece_range("my_cool_file.exe", 2)

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
        v1_range = t.v1_piece_range(6)
        prange = v1_range.ranges[0]
    else:
        prange = t.v2_piece_range("b.exe", 2)

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
