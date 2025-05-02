import os.path
import sys
from pathlib import Path


def get_size(path: Path) -> int:
    """
    Windows, helpfully, reports different sizes to stat,
    so we have to use the os.path.getsize() function instead
    """
    if sys.platform == "win32":
        return os.path.getsize(path)
    else:
        return path.stat().st_size
