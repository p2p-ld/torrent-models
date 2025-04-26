import bencode_rs

from torrent_models.torrent import TorrentCreate
from torrent_models.types import TorrentVersion

from .conftest import DATA_DIR


def test_create_basic(version):
    """
    Test that we can recreate the basic torrents exactly
    """

    paths = list((DATA_DIR / "basic").rglob("*"))
    create = TorrentCreate(
        paths=paths,
        path_root=DATA_DIR / "basic",
        trackers=["udp://example.com:6969"],
        piece_length=32 * (2**10),
        comment="test",
        created_by="qBittorrent v5.0.4",
        creation_date=1745400513,
        url_list="https://example.com/files",
        info={"source": "source"},
    )
    generated = create.generate(version=version)
    # pdb.set_trace()
    assert generated.torrent_version == TorrentVersion.__members__[version]
    bencoded = generated.bencode()
    with open(DATA_DIR / f"qbt_basic_{version}.torrent", "rb") as f:
        expected = f.read()

    # assert this first for easier error messages
    bdecoded = bencode_rs.bdecode(bencoded)
    expected_decoded = bencode_rs.bdecode(expected)
    assert bdecoded == expected_decoded

    # then test for serialized identity
    assert bencoded == expected


def test_create_libtorrent(libtorrent_pair):
    """
    Creating a torrent with libtorrent is the same as creating it with torrent_models
    :param libtorrent_pair:
    :return:
    """
    lt, generated = libtorrent_pair
    assert lt == generated.model_dump_torrent()
