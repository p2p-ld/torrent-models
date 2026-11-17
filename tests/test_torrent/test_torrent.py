import hashlib
import io
from pathlib import Path

import bencode_rs
import pytest

from torrent_models import KiB, LoadLimits, Torrent
from torrent_models.types import FileItem
from torrent_models.types.common import TorrentVersion

from ..conftest import DATA_DIR

ALL_TORRENTS = list(tf for tf in DATA_DIR.rglob("*.torrent") if "giant" not in tf.name)


def test_parse_hybrid():
    torrent = Torrent.read("tests/data/qbt_directory_hybrid.torrent")


def test_deep_nesting_is_refused():
    """Nesting this deep crashes the process unless decoding is limited"""
    with pytest.raises(bencode_rs.BencodeDecodeError):
        Torrent.read_stream(
            io.BytesIO(b"l" * 60000 + b"e" * 60000), context={"limits": LoadLimits.libtorrent()}
        )


def test_nesting_limit_can_be_changed():
    """Nested as deep as the limit is fine, and one more is refused"""
    data = b"d4:info" + b"l" * 9 + b"e" * 9 + b"e"
    with pytest.raises(bencode_rs.BencodeDecodeError):
        Torrent.read_stream(io.BytesIO(data), context={"limits": LoadLimits(max_depth=9)})
    # decodes, then fails validation since the info dict is a list
    with pytest.raises(ValueError):
        Torrent.read_stream(io.BytesIO(data), context={"limits": LoadLimits(max_depth=10)})


def test_limits_as_keywords():
    """Limits can be passed on their own, replacing the context's, which isn't changed"""
    data = b"d4:info" + b"l" * 9 + b"e" * 9 + b"e"
    with pytest.raises(bencode_rs.BencodeDecodeError):
        Torrent.read_stream(io.BytesIO(data), max_depth=9)
    context = {"limits": LoadLimits(max_depth=9)}
    with pytest.raises(ValueError, match="info"):
        Torrent.read_stream(io.BytesIO(data), context=context, max_depth=10)
    assert context == {"limits": LoadLimits(max_depth=9)}
    with pytest.raises(TypeError):
        Torrent.read_stream(io.BytesIO(data), max_dpeth=10)


def _deep_v2_torrent(path_depth: int) -> bytes:
    """A v2 torrent with one file, whose path has this many elements, counting the file name"""
    tree: dict = {b"": {b"length": 10, b"pieces root": hashlib.sha256(b"x").digest()}}
    tree = {b"file": tree}
    for i in reversed(range(path_depth - 1)):
        tree = {f"dir{i}".encode(): tree}
    info = {b"name": b"t", b"piece length": 16 * KiB, b"meta version": 2, b"file tree": tree}
    return bencode_rs.bencode({b"info": info, b"piece layers": {}})


def test_deepest_file_tree_loads():
    """
    With libtorrent's limits, a v2 file tree 96 deep, counting the file name,
    loads on every platform, and one any deeper is refused while decoding
    """
    context = {"limits": LoadLimits.libtorrent()}
    deepest = 96
    torrent = Torrent.read_stream(io.BytesIO(_deep_v2_torrent(deepest)), context=context)
    assert len(torrent.files[0].path.split("/")) == deepest
    with pytest.raises(bencode_rs.BencodeDecodeError):
        Torrent.read_stream(io.BytesIO(_deep_v2_torrent(deepest + 1)), context=context)


def test_padfiles_arent_files():
    """Padfiles aren't counted as files, even with other attrs besides ``p``"""
    files = [
        FileItem(path=["a"], length=5 * KiB),
        FileItem(path=[".pad", str(11 * KiB)], length=11 * KiB, attr=b"px"),
        FileItem(path=["b"], length=100),
    ]
    info = {"name": "t", "piece length": 16 * KiB, "pieces": bytes(40), "files": files}
    torrent = Torrent.model_validate({"info": info})
    assert torrent.n_files == 2
    assert torrent.total_size == 5 * KiB + 100
    assert [f.path for f in torrent.files] == ["a", "b"]
    with pytest.raises(ValueError):
        torrent.layout.file(f".pad/{11 * KiB}")


def test_download_path():
    """A torrent's files go in a directory named after it, unless there's only one"""
    one = {"name": "a.txt", "piece length": 16 * KiB, "pieces": bytes(20), "length": 100}
    assert [f.download_path for f in Torrent.model_validate({"info": one}).files] == ["a.txt"]
    files = [FileItem(path=["a"], length=100), FileItem(path=["dir", "b"], length=100)]
    many = {"name": "t", "piece length": 16 * KiB, "pieces": bytes(20), "files": files}
    torrent = Torrent.model_validate({"info": many})
    assert [f.download_path for f in torrent.files] == ["t/a", "t/dir/b"]


@pytest.mark.libtorrent
@pytest.mark.parametrize(
    "tfile",
    [pytest.param(tf, id=str(tf.name)) for tf in ALL_TORRENTS],
)
def test_infohash(tfile: Path):
    """
    Test that the infohash that we get from a torrent is the same as what libtorrent would compute
    """
    import libtorrent

    lt_torrent = libtorrent.load_torrent_file(str(tfile))
    t = Torrent.read(tfile)

    if t.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
        assert t.v1_infohash is not None
        assert lt_torrent.info_hashes.has_v1()
        assert t.v1_infohash == lt_torrent.info_hashes.v1.to_bytes().hex()
    if t.torrent_version in (TorrentVersion.v2, TorrentVersion.hybrid):
        assert t.v2_infohash is not None
        assert lt_torrent.info_hashes.has_v2()
        assert t.v2_infohash == lt_torrent.info_hashes.v2.to_bytes().hex()
    if t.torrent_version not in TorrentVersion:
        raise ValueError("Torrent not detecting version")
