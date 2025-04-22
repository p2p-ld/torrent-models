import warnings
from importlib.util import find_spec

__all__ = ["main"]

if find_spec("click"):

    from torrent_pydantic.cli import main
else:
    warnings.warn(
        "cli dependencies are not installed - install with torrent-pydantic[cli]", stacklevel=2
    )
