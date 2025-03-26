from pathlib import Path
from typing import Any
from typing import Literal as L

import bencode_rs
from pydantic import BaseModel, Field, model_validator

from torrent_pyd.types import (
    ByteStr,
    ByteUrl,
    FilePart,
    FileTree,
    PieceLength,
    Pieces,
    UnixDatetime,
    str_keys,
)

PieceLayers = dict[bytes, bytes]


class FileItem(BaseModel):
    length: int
    path: list[FilePart]
    attr: L[b"p"] | None = None


# class FileTree(RootModel):
#     root: dict[FileName,dict[L[''], FileTreeItem]]


class InfoDictRoot(BaseModel):
    """Fields shared by v1 and v2 infodicts"""

    name: ByteStr
    piece_length: PieceLength = Field(alias="piece length")
    source: ByteStr | None = None


class InfoDictV1(InfoDictRoot):

    pieces: Pieces
    length: int | None = None
    files: list[FileItem] | None = Field(None)

    @model_validator(mode="after")
    @classmethod
    def length_xor_files(cls, val: dict) -> dict:
        """
        There is also a key length or a key files, but not both or neither.
        If length is present then the download represents a single file,
        otherwise it represents a set of files which go in a directory structure.
        """
        if "length" in val or getattr(val, "length", None) is not None:
            assert (
                "files" not in val and getattr(val, "files", None) is None
            ), "Torrents may have `length` or `files` but not both."
        elif "files" in val or getattr(val, "files", None) is not None:
            assert (
                "length" not in val and getattr(val, "length", None) is None
            ), "Torrents may have `length` or `files` but not both."
        else:
            raise ValueError("Either `length` or `files` must be present")
        return val


class InfoDictV2(InfoDictRoot):
    meta_version: int = Field(2, alias="meta version")
    file_tree: FileTree = Field(alias="file tree")


class InfoDictHybrid(InfoDictV1, InfoDictV2):
    pass


class Torrent(BaseModel):
    announce: ByteUrl
    announce_list: list[list[ByteUrl]] | None = Field(default=None, alias="announce-list")
    comment: ByteStr | None = None
    created_by: ByteStr | None = Field(None, alias="created by")
    creation_date: UnixDatetime | None = None
    info: InfoDictV1 | InfoDictV2 | InfoDictHybrid = Field(..., union_mode="left_to_right")
    piece_layers: PieceLayers | None = Field(None, alias="piece layers")

    # @model_validator(mode="before")
    # def str_keys(cls, value: dict[bytes, Any]) -> dict[str, Any]:
    #     return {k.decode('utf-8'): v for k, v in value.items()}

    def __init__(__pydantic_self__, decoded: dict[bytes, Any] | None = None, **data: Any) -> None:
        if decoded is not None:
            decoded.update(data)
            data = decoded
        if any([isinstance(k, bytes) for k in data]):
            data = str_keys(data)
        super().__init__(**data)

    @classmethod
    def read(cls, path: Path | str) -> "Torrent":
        with open(path, "rb") as tfile:
            tdata = tfile.read()
        tdict = bencode_rs.bdecode(tdata)
        return Torrent(decoded=tdict)
