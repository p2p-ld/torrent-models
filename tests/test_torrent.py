from pathlib import Path

import bencode_rs

from torrent_models import Torrent


def test_parse_hybrid():
    torrent = Torrent.read("tests/data/qbt_directory_hybrid.torrent")


def test_infohash():
    """
    Test that the infohash that we get from a torrent is the same as what libtorrent would compute
    :return:
    """
    tfile = Path("/Users/jonny/torrents/nih-reporter-exporter-25-04-25.torrent")
    with open(tfile, "rb") as f:
        data = f.read()

    decoded = bencode_rs.bdecode(data)
    expected = decoded[b"info"]

    t = Torrent.read(tfile)
    info = bencode_rs.bdecode(
        bencode_rs.bencode(t.info.model_dump(exclude_none=True, by_alias=True))
    )

    assert expected[b"file tree"] == info[b"file tree"]
    assert expected == info
