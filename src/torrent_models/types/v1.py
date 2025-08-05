"""
Types used only in v1 (and hybrid) torrents
"""

import hashlib
from typing import Annotated, Self

from annotated_types import Ge
from pydantic import (
    AfterValidator,
    BeforeValidator,
    PlainSerializer,
    ValidationInfo,
    model_validator,
)
from pydantic_core.core_schema import SerializationInfo

from torrent_models.base import ConfiguredBase
from torrent_models.types.common import FilePart, PieceRange, SHA1Hash, _power_of_two, webseed_url

V1PieceLength = Annotated[int, AfterValidator(_power_of_two)]
"""
According to BEP 003: no specification, but "almost always a power of two",
so we validate that.
"""


def _validate_pieces(pieces: bytes | list[bytes]) -> list[bytes]:
    if isinstance(pieces, bytes):
        assert len(pieces) % 20 == 0, "Pieces length must be divisible by 20"
        pieces = [pieces[i : i + 20] for i in range(0, len(pieces), 20)]

    return pieces


def _serialize_pieces(
    pieces: list[bytes], info: SerializationInfo
) -> bytes | list[bytes] | list[str]:
    """Join piece lists to a big long byte string unless we're pretty printing"""
    if info.context and info.context.get("mode") == "print":
        ret = [p.hex() for p in pieces]
        if info.context.get("hash_truncate"):
            ret = [p[0:8] for p in ret]
        return ret
    return b"".join(pieces)


Pieces = Annotated[
    list[SHA1Hash], BeforeValidator(_validate_pieces), PlainSerializer(_serialize_pieces)
]


class FileItem(ConfiguredBase):
    length: Annotated[int, Ge(0)]
    path: list[FilePart]
    attr: bytes | None = None
    """
    BEP0047: A variable-length string. 
    When present the characters each represent a file attribute. 
    l = symlink, 
    x = executable, 
    h = hidden, 
    p = padding file. 
    Characters appear in no particular order and unknown characters should be ignored.
    """

    @property
    def is_padfile(self) -> bool:
        return self.attr is not None and b"p" in self.attr

    @model_validator(mode="after")
    def strict_padfile_naming(self, info: ValidationInfo) -> Self:
        """in strict mode, padfiles must be named `.pad/{length}"""
        if not self.is_padfile:
            return self
        if info.context and info.context.get("padding_path") == "strict":
            assert self.path == [
                ".pad",
                str(self.length),
            ], "strict mode - padfiles must be named `.pad/{length}`"
        return self


class FileItemRange(FileItem):
    """A File Item with a byte range, for use with V1PieceRange"""

    range_start: int
    range_end: int
    full_path: str
    """
    Path to be used with webseeds, includes `info.name` in the case of multifile torrents,
    so the webseed base can be directly joined with `full_path`
    """

    def webseed_url(self, base_url: str) -> str:
        return webseed_url(base_url, self.full_path)


class V1PieceRange(PieceRange):
    """
    Paths and byte ranges that correspond to a single v1
    """

    ranges: list[FileItemRange]
    piece_hash: SHA1Hash

    def validate_data(self, data: list[bytes]) -> bool:
        """
        Validate data against hash by concatenating bytes and comparing the SHA1 hash

        The user is responsible for providing all-zero bytestrings
        for any padding files in the indicated ranges
        """
        assert len(data) == len(
            self.ranges
        ), "Need to provide data chunks that correspond to each of the indicated file ranges"
        for range_, d in zip(self.ranges, data):
            assert (range_.range_end - range_.range_start) == len(d), (
                "Provided data chunks must match the sizes indicated by the "
                "start and end ranges of each file range"
            )

        hasher = hashlib.new("sha1")
        for d in data:
            hasher.update(d)
        return self.piece_hash == hasher.digest()
