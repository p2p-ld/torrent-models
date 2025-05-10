import sys
from enum import StrEnum
from typing import NotRequired, TypeAlias

from pydantic import (
    AnyUrl,
)

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


def _divisible_by_16kib(size: int) -> int:
    assert size >= (16 * (2**10)), "Size must be at least 16 KiB"
    assert size % (16 * (2**10)) == 0, "Size must be divisible by 16 KiB"
    return size


def _power_of_two(n: int) -> int:
    assert (n & (n - 1) == 0) and n != 0, "Piece size must be a power of two"
    return n


TrackerFields = TypedDict(
    "TrackerFields",
    {"announce": AnyUrl | str, "announce-list": NotRequired[list[list[AnyUrl]] | list[list[str]]]},
)
"""The `announce` and `announce-list`"""
