from torrent_pydantic.torrent import Torrent


def test_parse_hybrid():
    torrent = Torrent.read("tests/data/qbt_directory_hybrid.torrent")
