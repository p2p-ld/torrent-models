import sys
from datetime import datetime
from enum import StrEnum
from typing import Annotated, NotRequired, TypeAlias, Union, cast
from typing import Literal as L

from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    PlainSerializer,
    SerializationInfo,
)

if sys.version_info < (3, 12):
    from typing_extensions import TypeAliasType, TypedDict
else:
    from typing import TypeAliasType, TypedDict


class TorrentVersion(StrEnum):
    """Version of the bittorrent .torrent file spec"""

    v1 = "v1"
    v2 = "v2"
    hybrid = "hybrid"


def _timestamp_to_datetime(val: int | datetime) -> datetime:
    if isinstance(val, int | float):
        val = datetime.fromtimestamp(val)
    return val


def _datetime_to_timestamp(val: datetime) -> int:
    return round(val.timestamp())


UnixDatetime = Annotated[
    datetime, BeforeValidator(_timestamp_to_datetime), PlainSerializer(_datetime_to_timestamp)
]


# class ByteStrProtocol(EncoderProtocol):
#     @classmethod
#     def decode(cls, data: bytes) -> bytes:
#         return data
#
#     @classmethod
#     def encode(cls, data: bytes) -> bytes:
#         return data
#
#     @classmethod
#     def get_json_format(cls) -> str:
#         return 'byte-str'

EXCLUDE_STRINGIFY = ("piece_layers", "piece layers", "path")


def str_keys(
    value: dict | list | BaseModel, _isdict: bool | None = None
) -> dict | list | BaseModel:
    """
    Convert the byte-encoded keys of a bencoded dictionary to strings,
    avoiding value of keys we know to be binary encoded like piece layers.

    .. note: Performance Notes

        AKA why this function looks so weird.

        doing isinstance check at the start is slightly faster than EAFP and allocating new_value,
        but use th internal bool _isdict to avoid doing it twice when we have already checked
        the argument's type in a parent call

        since we only call this with fresh output from bencode, we know that we only have
        python builtins, and therefore we can check with the classname rather than isinstance,
        which is slightly faster. this means that this function is *not* a general purpose function,
        and should only be used on freshly decoded bencoded data!

        We iterate over lists in the ``dict`` leg rather than in the function root to avoid the
        final double type check for leaf nodes, checking only if they are dictionaries.
    """

    if _isdict or value.__class__.__name__ == "dict":
        new_value = {}
        value = cast(dict, value)
        for k, v in value.items():
            try:
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
            except UnicodeDecodeError:
                # fine, e.g. for piece maps whose keys are not utf-8 encoded
                # any invalid keys will get caught in validation
                pass

            if k in EXCLUDE_STRINGIFY:
                new_value[k] = v
                continue

            if v.__class__.__name__ == "dict":
                v = str_keys(v, _isdict=True)
            elif v.__class__.__name__ == "list":
                v = [str_keys(item) for item in v]
            new_value[k] = v
        return new_value
    else:
        return value


def str_keys_list(value: list[dict | BaseModel]) -> list[dict | list | BaseModel]:
    return [str_keys(v) for v in value]


def _to_str(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return value


def _to_bytes(value: str | bytes, info: SerializationInfo) -> bytes | str:
    if info.context and info.context.get("mode") == "print":
        return str(value)

    if isinstance(value, str):
        value = value.encode("utf-8")
    elif isinstance(value, AnyUrl):
        value = str(value).encode("utf-8")
    else:
        value = str(value).encode("utf-8")
    return value


ByteStr = Annotated[str, PlainSerializer(_to_bytes)]
ByteUrl = Annotated[AnyUrl, PlainSerializer(_to_bytes)]

FileName: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
FilePart: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""


def _divisible_by_16kib(size: int) -> int:
    assert size > (16 * (2**10)), "Size must be at least 16 KiB"
    assert size % (16 * (2**10)) == 0, "Size must be divisible by 16 KiB"
    return size


def _power_of_two(n: int) -> int:
    assert (n & (n - 1) == 0) and n != 0, "Piece size must be a power of two"
    return n


def _validate_size(size: int) -> int:
    assert _power_of_two(size), "Piece size must be a power of two"
    assert size >= 16 * (2**10), "Piece size must be at least 16KiB"
    # assert _divisible_by_16kib(size), "Piece size must be divisible by 16kib and positive"
    return size


V1PieceLength = Annotated[int, AfterValidator(_power_of_two)]
V2PieceLength = Annotated[int, AfterValidator(_divisible_by_16kib)]


def _validate_pieces(pieces: bytes | list[bytes]) -> list[bytes]:
    if isinstance(pieces, bytes):
        assert len(pieces) % 20 == 0, "Pieces length must be divisible by 20"
        pieces = [pieces[i : i + 20] for i in range(0, len(pieces), 20)]
    else:
        assert all([len(piece) == 20 for piece in pieces]), "Pieces length must be divisible by 20"

    return pieces


def _serialize_pieces(
    pieces: list[bytes], info: SerializationInfo
) -> bytes | list[bytes] | list[str]:
    """Join piece lists to a big long byte string unless we're pretty printing"""
    if info.context and info.context.get("mode") == "print":
        if info.context.get("hash_repr") != "bytes":
            pieces = [p.hex() for p in pieces]
        if info.context.get("hash_truncate"):
            pieces = [p[0:8] for p in pieces]
        return pieces
    return b"".join(pieces)


Pieces = Annotated[
    list[bytes], BeforeValidator(_validate_pieces), PlainSerializer(_serialize_pieces)
]


def _serialize_v2_hash(value: bytes, info: SerializationInfo) -> bytes | str | list[str]:
    if info.context and info.context.get("mode") == "print":
        if info.context.get("hash_repr") != "bytes":
            value = value.hex()
        if info.context.get("hash_truncate"):
            value = value[0:8]
        # split layers
        if len(value) > 64:
            value = [value[i : i + 64] for i in range(0, len(value), 64)]

    return value


PieceLayerItem = Annotated[bytes, PlainSerializer(_serialize_v2_hash)]

PieceLayersType = dict[PieceLayerItem, PieceLayerItem]

FileTreeItem = TypedDict(
    "FileTreeItem", {"length": int, "pieces root": NotRequired[PieceLayerItem]}
)

FileTreeType: TypeAlias = TypeAliasType(  # type: ignore
    "FileTreeType", dict[bytes, Union[dict[L[""], FileTreeItem], "FileTreeType"]]  # type: ignore
)


class FileItem(BaseModel):
    length: int
    path: list[FilePart]
    attr: L[b"p"] | None = None
