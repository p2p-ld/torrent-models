import sys
from abc import abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NotRequired, TypeAlias
from urllib.parse import quote

from annotated_types import Ge, Len
from pydantic import AfterValidator, AnyUrl, BaseModel, Field

from torrent_models.base import ConfiguredBase
from torrent_models.types.serdes import ByteStr

if sys.version_info < (3, 12):
    from typing_extensions import TypedDict
else:
    from typing import TypedDict


class TorrentVersion(StrEnum):
    """Version of the bittorrent .torrent file spec"""

    v1 = "v1"
    v2 = "v2"
    hybrid = "hybrid"


FileName: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
FilePart: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
SHA1Hash = Annotated[bytes, Len(20, 20)]
SHA256Hash = Annotated[bytes, Len(32, 32)]


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

    @abstractmethod
    def validate_data(self, data: list[bytes]) -> bool:
        """Check that the provided data matches the piece or root hash"""


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
