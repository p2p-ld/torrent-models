from importlib.metadata import version

DEFAULT_TORRENT_CREATOR = f"torrent-models ({version('torrent-models')})"
EXCLUDE_FILES = (".DS_Store", "Thumbs.db")

KiB = 2**10
MiB = 2**20
GiB = 2**30
TiB = 2**40


class size:
    """Convenience accessor/importer for sizes"""

    KiB = KiB
    MiB = MiB
    GiB = GiB
    TiB = TiB


BLOCK_SIZE = 16 * KiB
