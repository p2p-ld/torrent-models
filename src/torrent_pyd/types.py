from typing import Annotated, TypeAlias, TypeAliasType, TypedDict, Union
from datetime import datetime

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, BaseModel, EncoderProtocol, EncodedStr, AnyUrl, Field

def _timestamp_to_datetime(val: int | datetime) -> datetime:
    if isinstance(val, int | float):
        val = datetime.fromtimestamp(val)
    return val

def _datetime_to_timestamp(val: datetime) -> int:
    return round(val.timestamp())

UnixDatetime = Annotated[datetime, BeforeValidator(_timestamp_to_datetime), PlainSerializer(_datetime_to_timestamp)]


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

def str_keys(value: dict | BaseModel) -> dict | BaseModel:
    if isinstance(value, dict):
        # FIXME: use comprehension
        new_value = {}
        for k,v in value.items():
            if isinstance(k, bytes):
                k = k.decode('utf-8')
            if isinstance(v, dict):
                v = str_keys(v)
            new_value[k] = v
        return new_value
    else:
        return value

def str_keys_list(value: list[dict | BaseModel]) -> list[dict | BaseModel]:
    return [str_keys(v) for v in value]

def _to_str(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    return value

def _to_bytes(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode('utf-8')
    return value


ByteStr = Annotated[str, BeforeValidator(_to_str), PlainSerializer(_to_bytes)]
ByteUrl = Annotated[AnyUrl, BeforeValidator(_to_str), PlainSerializer(_to_bytes)]

FileName: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""
FilePart: TypeAlias = ByteStr
"""Placeholder in case specific validation is needed for filenames"""

def _divisible_by_16kib(size: int) -> bool:
    if size < 0:
        return False
    return size % (16 * (2**10)) == 0

def _power_of_two(n: int) -> int:
    return (n & (n-1) == 0) and n != 0

def _validate_size(size: int) -> int:
    assert _power_of_two(size), "Piece size must be a power of two"
    assert size >= 16 * (2**10), "Piece size must be at least 16KiB"
    # assert _divisible_by_16kib(size), "Piece size must be divisible by 16kib and positive"
    return size



PieceLength = Annotated[int, AfterValidator(_validate_size)]

def _validate_pieces(pieces: bytes) -> list[bytes]:
    assert len(pieces) % 20 == 0, "Pieces length must be divisible by 20"
    pieces = [pieces[i:i+20] for i in range(0, len(pieces), 20)]
    return pieces

Pieces = Annotated[bytes, AfterValidator(_validate_pieces)]

class FileTreeItem(BaseModel):
    length: int
    pieces_root: bytes | None = Field(alias="pieces root")

FileTree: TypeAlias = TypeAliasType("FileTree", Annotated[dict[ByteStr, Union[FileTreeItem, "FileTree"]], BeforeValidator(str_keys)])

