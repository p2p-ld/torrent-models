from functools import cached_property
from math import ceil
from typing import Annotated, Self
from typing import Literal as L

from annotated_types import Gt, MinLen
from pydantic import BaseModel, Field, model_validator

from torrent_models.base import ConfiguredBase
from torrent_models.types import (
    ByteStr,
    FilePart,
    FileTreeItem,
    FileTreeType,
    Pieces,
    V1PieceLength,
    V2PieceLength,
)
from torrent_models.v2 import FileTree


class FileItem(BaseModel):
    length: int
    path: list[FilePart]
    attr: L[b"p"] | None = None


class InfoDictRoot(ConfiguredBase):
    """Fields shared by v1 and v2 infodicts"""

    name: ByteStr
    source: ByteStr | None = None


class InfoDictV1Base(InfoDictRoot):
    pieces: Pieces | None = None
    length: Annotated[int, Gt(0)] | None = None
    files: Annotated[list[FileItem], MinLen(1)] | None = Field(None)
    piece_length: V1PieceLength = Field(alias="piece length")

    @cached_property
    def total_length(self) -> int:
        """Total length of all files, in bytes"""
        total = 0
        if not self.files:
            return total

        for f in self.files:
            total += f.length
        return total

    @model_validator(mode="after")
    def expected_n_pieces(self) -> Self:
        """We have the expected number of pieces given the sizes implied by our file dict"""
        if self.pieces is None:
            return self
        n_pieces = ceil(self.total_length / self.piece_length)
        assert n_pieces == len(self.pieces), (
            f"Expected {n_pieces} pieces for torrent with "
            f"total length {self.total_length} and piece_length"
            f"{self.piece_length}"
            f"Got {len(self.pieces)}"
        )
        return self


class InfoDictV1(InfoDictV1Base):
    """An infodict from a valid V1 torrent"""

    pieces: Pieces

    @model_validator(mode="after")
    def length_xor_files(self) -> Self:
        """
        There is also a key length or a key files, but not both or neither.
        If length is present then the download represents a single file,
        otherwise it represents a set of files which go in a directory structure.
        """
        assert bool(self.length) != bool(
            self.files
        ), "V1 Torrents must have a `length` or `files`,  but not both."
        return self


class InfoDictV1Create(InfoDictV1Base):
    """v1 Infodict that may or may not have its pieces hashed yet"""

    pass


class InfoDictV2Base(InfoDictRoot):
    meta_version: int = Field(2, alias="meta version")
    file_tree: FileTreeType | None = Field(None, alias="file tree")
    piece_length: V2PieceLength = Field(alias="piece length")

    @cached_property
    def flat_tree(self) -> dict[str, FileTreeItem]:
        """Flattened file tree! mapping full paths to tree items"""
        if self.file_tree is None:
            return {}
        else:
            return FileTree.flatten_tree(self.file_tree)

    @cached_property
    def total_length(self) -> int:
        """
        Total length of all files, in bytes.
        """
        total_length = 0
        for file in self.flat_tree.values():
            total_length += file["length"]
        return total_length


class InfoDictV2(InfoDictV2Base):
    """An infodict from a valid V2 torrent"""

    file_tree: FileTreeType = Field(alias="file tree")


class InfoDictV2Create(InfoDictV2Base):
    pass


class InfoDictHybridCreate(InfoDictV1Create, InfoDictV2Create):
    """An infodict of a hybrid torrent that may or may not have its pieces hashed yet"""

    name: ByteStr | None = None
    piece_length: V1PieceLength | V2PieceLength | None = Field(None, alias="piece length")


class InfoDictHybrid(InfoDictV1, InfoDictV2):
    """An infodict of a valid v1/v2 hybrid torrent"""

    piece_length: V2PieceLength = Field(alias="piece length")
