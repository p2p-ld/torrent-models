from torrent_pyd.torrent import Torrent
import bencode_rs

def test_parse_hybrid():
    torrent = Torrent.read('tests/data/qbt_directory_hybrid.torrent')
