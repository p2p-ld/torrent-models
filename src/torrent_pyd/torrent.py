from typing import Annotated, Any, Literal as L, TypedDict
from pydantic import BaseModel, AnyUrl, Field, RootModel, model_validator, BeforeValidator
from pathlib import Path
import bencode_rs
from torrent_pyd.types import UnixDatetime, FileName, PieceLength, Pieces, FilePart, FileTree, ByteStr, ByteUrl, str_keys, str_keys_list


PieceLayers = dict[bytes, bytes]



class FileItem(BaseModel):
    length: int
    path: list[FilePart]

class PadFileItem(FileItem):
    attr: L['p']

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
    files: Annotated[list[FileItem | PadFileItem], BeforeValidator(str_keys_list)] | None = None

    @model_validator(mode="after")
    @classmethod
    def length_xor_files(cls, val: dict) -> dict:
        """
        There is also a key length or a key files, but not both or neither.
        If length is present then the download represents a single file,
        otherwise it represents a set of files which go in a directory structure.
        """
        if 'length' in val:
            assert 'files' not in val, "Torrents may have `length` or `files` but not both."
        elif 'files' in val:
            assert 'length' not in val, "Torrents may have `length` or `files` but not both."
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
    announce_list: list[list[ByteUrl]] | None = Field(default = None, alias="announce-list")
    comment: ByteStr | None = None
    created_by: ByteStr | None = Field(None, alias="created by")
    creation_date: UnixDatetime | None = None
    info: Annotated[InfoDictV1 | InfoDictV2 | InfoDictHybrid, BeforeValidator(str_keys)]
    piece_layers: PieceLayers | None = None

    # @model_validator(mode="before")
    # def str_keys(cls, value: dict[bytes, Any]) -> dict[str, Any]:
    #     return {k.decode('utf-8'): v for k, v in value.items()}

    @classmethod
    def read(cls, path: Path | str) -> "Torrent":
        with open('tests/data/qbt_directory_hybrid.torrent', 'rb') as tfile:
            tdata = tfile.read()
        tdict = bencode_rs.bdecode(tdata)
        tdict = {k.decode('utf-8'): v for k, v in tdict.items()}
        return Torrent(**tdict)


