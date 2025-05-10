"""
Types used only in v1 (and hybrid) torrents
"""

from typing import Annotated
from typing import Literal as L

from pydantic import AfterValidator, BaseModel, BeforeValidator, PlainSerializer
from pydantic_core.core_schema import SerializationInfo

from torrent_models.types.common import FilePart, _power_of_two

V1PieceLength = Annotated[int, AfterValidator(_power_of_two)]
"""
According to BEP 003: no specification, but "almost always a power of two",
so we validate that.
"""


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
        ret = [p.hex() for p in pieces]
        if info.context.get("hash_truncate"):
            ret = [p[0:8] for p in ret]
        return ret
    return b"".join(pieces)


Pieces = Annotated[
    list[bytes], BeforeValidator(_validate_pieces), PlainSerializer(_serialize_pieces)
]


class FileItem(BaseModel):
    length: int
    path: list[FilePart]
    attr: L[b"p"] | None = None
