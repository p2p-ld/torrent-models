"""
Types used only in v1 (and hybrid) torrents
"""

import hashlib
from pathlib import Path
from typing import Annotated, Self

from annotated_types import Ge
from pydantic import (
    AfterValidator,
    BeforeValidator,
    PlainSerializer,
    ValidationInfo,
    computed_field,
    model_validator,
)
from pydantic_core.core_schema import SerializationInfo

from torrent_models.base import ConfiguredBase
from torrent_models.types.common import (
    FilePart,
    PieceRange,
    SHA1Hash,
    _power_of_two,
    _read_range,
    webseed_url,
)

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

    @classmethod
    def padfile(cls, length: int) -> Self:
        """A padfile, named ``.pad/{length}`` as BEP 47 recommends"""
        return cls(length=length, path=[".pad", str(length)], attr=b"p")

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
    Paths and byte ranges that correspond to a single v1 piece
    """

    piece_length: V1PieceLength
    ranges: list[FileItemRange]
    piece_hash: SHA1Hash

    @computed_field  # type: ignore[prop-decorator]
    @property
    def offset(self) -> int:
        """
        Byte offset of the start of the piece within the whole torrent,
        with all files (including padfiles) laid end to end
        """
        return self.piece_idx * self.piece_length

    @property
    def size(self) -> int:
        """
        Bytes of data in the piece, including padfiles.
        Only the last piece of the torrent is shorter than the piece length.
        """
        return sum(r.range_end - r.range_start for r in self.ranges)

    @property
    def padding(self) -> int:
        padding = 0
        for r in reversed(self.ranges):
            if not r.is_padfile:
                break
            padding += r.range_end - r.range_start
        return padding

    def _hash_matches(self, data: list[bytes], length: int) -> bool:
        hasher = hashlib.new("sha1")
        for d in data:
            hasher.update(d)
        hasher.update(bytes(self.size - length))
        return self.piece_hash == hasher.digest()

    def read(self, root: Path) -> bytes:
        """See :meth:`.PieceRange.read`"""
        return b"".join(
            (
                bytes(r.range_end - r.range_start)
                if r.is_padfile
                else _read_range(root, r.full_path, r.range_start, r.range_end)
            )
            for r in self.ranges
        )
