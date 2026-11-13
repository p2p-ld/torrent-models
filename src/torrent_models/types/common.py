from abc import abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NotRequired, TypedDict
from urllib.parse import quote

from annotated_types import Ge, Len
from pydantic import AfterValidator, AnyUrl, BaseModel, Field, PlainSerializer, SerializationInfo

from torrent_models.base import ConfiguredBase
from torrent_models.types.serdes import ByteStr


class TorrentVersion(StrEnum):
    """Version of the bittorrent .torrent file spec"""

    v1 = "v1"
    v2 = "v2"
    hybrid = "hybrid"


type FileName = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
type FilePart = ByteStr
"""Placeholder in case specific validation is needed for filenames"""


def _serialize_hash(value: bytes, info: SerializationInfo) -> bytes | str:
    if info.context and info.context.get("mode") == "print":
        v = value.hex()
        if info.context.get("hash_truncate"):
            v = v[0:8]
        return v
    else:
        return value


SHA1Hash = Annotated[bytes, Len(20, 20), PlainSerializer(_serialize_hash)]
SHA256Hash = Annotated[bytes, Len(32, 32), PlainSerializer(_serialize_hash)]


TrackerFields = TypedDict(
    "TrackerFields",
    {
        "announce": NotRequired[AnyUrl | str],
        "announce-list": NotRequired[list[list[AnyUrl]] | list[list[str]]],
    },
)
"""The `announce` and `announce-list`"""


def _is_abs(path: Path) -> Path:
    """File must be absolute. if it is relative and still exists, make absolute"""
    if path.exists() and not path.is_absolute():
        path = path.resolve()
    assert path.is_absolute(), "Path must be absolute"
    return path


def _is_rel(path: Path) -> Path:
    """File must be relative"""
    assert not path.is_absolute(), "Path must be relative"
    return path


AbsPath = Annotated[Path, AfterValidator(_is_abs)]
RelPath = Annotated[Path, AfterValidator(_is_rel)]


def _divisible_by_16kib(size: int) -> int:
    assert size >= (16 * (2**10)), "Size must be at least 16 KiB"
    assert size % (16 * (2**10)) == 0, "Size must be divisible by 16 KiB"
    return size


def _power_of_two(n: int) -> int:
    assert (n & (n - 1) == 0) and n != 0, "Piece size must be a power of two"
    return n


class GenericFileItem(ConfiguredBase):
    """
    File metadata object with file information from both v1 and v2 representations

    For use with :class:`.Torrent.files`
    """

    path: FileName
    download_path: str
    """
    Where the file goes, relative to the download directory, the way clients lay it out:
    in a directory named after the torrent, unless it's the torrent's only file
    """
    length: Annotated[int, Ge(0)]
    attr: bytes | None = None
    pieces_root: bytes | None = Field(None, alias="pieces root")


class PieceRange(BaseModel):
    """
    Parent model for v1 and v2 piece ranges.

    Piece ranges provide some description of paths and byte ranges that correspond to a single
    verifiable piece and a method for verifying data against them.

    Since v1 and v2 data models are substantially different,
    their sub-models are also quite different, but provide a common interface through this ABC
    """

    piece_idx: int
    """
    Index of the piece within the whole torrent,
    which peers use to refer to it in the peer wire protocol.
    """
    piece_length: int
    """Piece length of the torrent, in bytes"""

    @property
    @abstractmethod
    def size(self) -> int:
        """Bytes of data in the piece"""

    @property
    def padding(self) -> int:
        """
        Bytes of padfiles at the end of the piece, counted in :attr:`.size`.
        They're all zeros, so they needn't be downloaded (BEP 47),
        and :meth:`.validate_data` fills them in if they're left out.
        """
        return 0

    def validate_data(self, data: list[bytes] | bytes | Path) -> bool:
        """
        Whether the piece's data matches its piece or root hash.

        The data can be given in chunks split up any way, e.g. one per file,
        or in 16 KiB blocks as peers send them, as long as they add up to the whole piece.
        The padfiles at the end of the piece (:attr:`.padding`) can be left out,
        and are filled in with zeros. Any padfiles before them must be in the data, as zeros.

        Or give the directory the torrent was downloaded to, to read the data from there
        (see :meth:`.read`). That's False if any of the data isn't on disk,
        and raises ValueError if a path in the torrent would end up outside of it.
        """
        if isinstance(data, Path):
            try:
                data = self.read(data)
            except (FileNotFoundError, EOFError):
                return False
        if isinstance(data, bytes):
            data = [data]

        length = sum(len(d) for d in data)
        assert length in (self.size, self.size - self.padding), (
            f"Provided data must add up to the size of the piece ({self.size} bytes), "
            f"or that without the padding at its end ({self.size - self.padding} bytes), "
            f"got {length}"
        )
        return self._hash_matches(data, length)

    @abstractmethod
    def _hash_matches(self, data: list[bytes], length: int) -> bool:
        """
        Whether the data matches the piece's hash, once it's padded with zeros
        from ``length`` bytes up to :attr:`.size`
        """

    @abstractmethod
    def read(self, root: Path) -> bytes:
        """
        The piece's data, from the files under ``root``, the directory the torrent was
        downloaded to, which ``full_path`` is relative to. Padfiles are zeros, and needn't exist.
        Raises FileNotFoundError or EOFError if any of the data isn't there,
        and ValueError if a path in the torrent would end up outside of ``root``.
        """


def safe_join(root: Path, path: str) -> Path:
    """
    ``root / path``, refusing paths that would end up outside of root.

    Paths in torrents and zips come from strangers.
    """
    root = root.resolve()
    joined = (root / path).resolve()
    if not joined.is_relative_to(root):
        raise ValueError(f"{path} is outside of {root}")
    return joined


def _read_range(root: Path, path: str, start: int, end: int) -> bytes:
    """
    Bytes [start, end) of a file under ``root``, see :func:`.safe_join`.
    Raises EOFError if it's too short.
    """
    full = safe_join(root, path)
    with open(full, "rb") as f:
        f.seek(start)
        data = f.read(end - start)
    if len(data) < end - start:
        raise EOFError(f"{full} ends before byte {end}")
    return data


def webseed_url(base_url: str, path: str) -> str:
    """
    Given some base url that is to be used as a webseed url and a path within a torrent file,
    get the full url that should be requested from the webseed server
    - leave url unchanged in the case of single file torrents
    - quote path segments
    - handle duplicate leading/trailing slashes
    """
    if base_url.endswith(path) or base_url.endswith(quote(path)):
        url = base_url
    else:
        # webseed url must be a directory, so we quote the path segments and append
        url_base = base_url.rstrip("/")
        path_parts = [quote(part) for part in path.split("/")]
        url = "/".join([url_base, *path_parts])
    return url
