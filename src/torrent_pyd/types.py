import sys
from datetime import datetime
from typing import Annotated, NotRequired, TypeAlias, TypedDict
from typing import Literal as L

from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    PlainSerializer,
)

if sys.version_info < (3, 12):
    from typing_extensions import TypeAliasType
else:
    from typing import TypeAlias as TypeAliasType


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


def str_keys_list(value: list[dict | BaseModel]) -> list[dict | BaseModel]:
    return [str_keys(v) for v in value]


def _to_str(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return value


def _to_bytes(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return value


ByteStr = Annotated[str, PlainSerializer(_to_bytes)]
ByteUrl = Annotated[AnyUrl, PlainSerializer(_to_bytes)]

FileName: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
FilePart: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""


def _divisible_by_16kib(size: int) -> bool:
    if size < 0:
        return False
    return size % (16 * (2**10)) == 0


def _power_of_two(n: int) -> int:
    return (n & (n - 1) == 0) and n != 0


def _validate_size(size: int) -> int:
    assert _power_of_two(size), "Piece size must be a power of two"
    assert size >= 16 * (2**10), "Piece size must be at least 16KiB"
    # assert _divisible_by_16kib(size), "Piece size must be divisible by 16kib and positive"
    return size


PieceLength = Annotated[int, AfterValidator(_validate_size)]


def _validate_pieces(pieces: bytes) -> list[bytes]:
    assert len(pieces) % 20 == 0, "Pieces length must be divisible by 20"
    pieces = [pieces[i : i + 20] for i in range(0, len(pieces), 20)]
    return pieces


Pieces = Annotated[bytes, AfterValidator(_validate_pieces), PlainSerializer(lambda x: b"".join(x))]

FileTreeItem = TypedDict("FileTreeItem", {"length": int, "pieces root": NotRequired[bytes]})

FileTree: TypeAlias = TypeAliasType(
    "FileTree", Annotated[dict[bytes, dict[L[""], FileTreeItem], "FileTree"], "ft"]
)
