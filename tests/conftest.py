import sys
from pathlib import Path

import pytest
from _pytest.python import Function

from .fixtures import *

DATA_DIR = Path(__file__).parent / "data"


def pytest_collection_modifyitems(config: pytest.Config, items: list[Function]) -> None:
    # don't run libtorrent tests on windows
    if sys.platform == "win32":
        skip_lt = pytest.mark.skip(reason="libtorrent python wheels are bugged in windows!")
        for item in items:
            if item.get_closest_marker("libtorrent"):
                item.add_marker(skip_lt)
