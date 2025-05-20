import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NotRequired, TypeAlias

from annotated_types import Len
from pydantic import AfterValidator, AnyUrl

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
    {"announce": AnyUrl | str, "announce-list": NotRequired[list[list[AnyUrl]] | list[list[str]]]},
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
