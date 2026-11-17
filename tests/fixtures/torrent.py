from pathlib import Path

import pytest

from torrent_models import TorrentVersion


@pytest.fixture
def basic_torrents(version: TorrentVersion) -> Path:
    from ..conftest import DATA_DIR

    return DATA_DIR / f"qbt_basic_{version}.torrent"
