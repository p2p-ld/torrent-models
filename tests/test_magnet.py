import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from torrent_models import Torrent, TorrentVersion
from torrent_models.magnet import MagnetLink

MAGNETS = {
    "v1": "magnet:?xt=urn:btih:631a31dd0a46257d5078c0dee4e66e26f73e42ac&dn=bittorrent-v1",
    "hybrid": (
        "magnet:?xt=urn:btih:631a31dd0a46257d5078c0dee4e66e26f73e42ac"
        "&xt=urn:btmh:1220d8dd32ac93357c368556af3ac1d95c9d76bd0dff6fa9833ecdac3d53134efabb"
        "&dn=bittorrent-v1-v2-hybrid-test"
    ),
    "v2": (
        "magnet:?xt=urn:btmh:1220caf1e1c30e81cb361b9ee167c4aa64228a7fa4fa9f6105232b28ad099f3a302e"
        "&dn=bittorrent-v2-test"
    ),
    "trackers": (
        "magnet:?xt=urn:btih:631a31dd0a46257d5078c0dee4e66e26f73e42ac"
        "&tr=http%3A%2F%2Fexample.com%2Fannounce"
        "&tr=udp%3A%2F%2Fexample.com%3A6969%2Fannounce"
    ),
    "single_tracker": (
        "magnet:?xt=urn:btih:631a31dd0a46257d5078c0dee4e66e26f73e42ac"
        "&tr=http%3A%2F%2Fexample.com%2Fannounce"
    ),
    "full": (
        "magnet:?xt=urn:btih:631a31dd0a46257d5078c0dee4e66e26f73e42ac"
        "&xt=urn:btmh:1220d8dd32ac93357c368556af3ac1d95c9d76bd0dff6fa9833ecdac3d53134efabb"
        "&dn=bittorrent-v1-v2-hybrid-test"
        "&tr=http%3A%2F%2Fexample.com%2Fannounce"
        "&tr=udp%3A%2F%2Fexample.com:6969%2Fannounce"
        "&xl=12345"
        "&ws=http%3A%2F%2Fexample.com%2Ffile1"
        "&ws=http%3A%2F%2Fexample.com%2Ffile2"
        "&so=1,2,3,4-6"
    ),
}


@pytest.mark.parametrize("magnet", [pytest.param(MAGNETS[k], id=k) for k in MAGNETS])
def test_magnet_roundtrip(magnet: str):
    """Magnet links can be roundtripped identically, ignoring order"""
    inst = MagnetLink.parse(magnet)
    rendered = inst.render()
    expected = parse_qs(urlparse(magnet).query)
    actual = parse_qs(urlparse(rendered).query)
    assert expected == actual


def test_magnet_prepend_multihash():
    """
    v2 infohashes need to have 1220 prepended to indicate they are a sha256 hash
    """
    infohash = hashlib.sha256(b"sup").hexdigest()
    assert not infohash.startswith("1220")
    magnet = MagnetLink(v2_infohash=infohash).render()
    assert "urn:btmh:1220" in magnet


@pytest.mark.parametrize("magnet", [pytest.param(MAGNETS[k], id=k) for k in MAGNETS])
def test_magnet_ordering(magnet: str):
    """
    infohashes and trackers should come first
    """
    link = MagnetLink.parse(magnet).render()
    query = parse_qs(urlparse(link).query)
    for i, key in enumerate(query):
        assert i == 0
        assert key == "xt"
        break


def test_from_torrentfile(basic_torrents: Path, version: TorrentVersion):
    """
    We can make magnet links from torrentfiles
    """
    t = Torrent.read(basic_torrents)
    t.announce_list = [["http://example.com/announce"]]
    magnet = t.magnet
    rendered = magnet.render()
    if version == TorrentVersion.v1:
        infohash_part = f"?xt=urn:btih:{t.v1_infohash}"
    elif version == TorrentVersion.v2:
        infohash_part = f"?xt=urn:btmh:1220{t.v2_infohash}"
    elif version == TorrentVersion.hybrid:
        infohash_part = f"?xt=urn:btih:{t.v1_infohash}" f"&xt=urn:btmh:1220{t.v2_infohash}"
    else:
        raise ValueError("What kinda torrent are you trying to pull buster")

    expected = (
        f"magnet:{infohash_part}"
        "&tr=udp%3A%2F%2Fexample.com%3A6969"
        "&tr=http%3A%2F%2Fexample.com%2Fannounce"
        f"&dn=qbt_basic_{str(version)}.torrent"
        f"&xl={t.total_size}"
    )

    assert rendered == expected
