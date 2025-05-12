from importlib.metadata import version

DEFAULT_TORRENT_CREATOR = f"torrent-models ({version('torrent-models')})"
EXCLUDE_FILES = (".DS_Store", "Thumbs.db")
BLOCK_SIZE = 16 * (2**10)
