from math import ceil
from pathlib import Path
from typing import Any, Self, cast
from typing import Literal as L

import bencode_rs
import humanize
from pydantic import Field, model_validator
from rich import print
from rich.console import Group
from rich.pretty import Pretty
from rich.table import Table

from torrent_models.base import ConfiguredBase
from torrent_models.const import DEFAULT_TORRENT_CREATOR
from torrent_models.info import (
    InfoDictHybrid,
    InfoDictV1,
    InfoDictV1Base,
    InfoDictV2,
    InfoDictV2Base,
)
from torrent_models.types import (
    ByteStr,
    ByteUrl,
    FileItem,
    FileTreeItem,
    ListOrValue,
    PieceLayersType,
    TorrentVersion,
    UnixDatetime,
    str_keys,
)
from torrent_models.types.v2 import FileTree


class TorrentBase(ConfiguredBase):
    announce: ByteUrl
    announce_list: list[list[ByteUrl]] | None = Field(default=None, alias="announce-list")
    comment: ByteStr | None = None
    created_by: ByteStr | None = Field(DEFAULT_TORRENT_CREATOR, alias="created by")
    creation_date: UnixDatetime | None = Field(default=None, alias="creation date")
    info: InfoDictV1 | InfoDictV2 | InfoDictHybrid = Field(..., union_mode="left_to_right")
    piece_layers: PieceLayersType | None = Field(None, alias="piece layers")
    url_list: ListOrValue[ByteUrl] | None = Field(
        None, alias="url-list", description="List of webseeds"
    )

    @property
    def webseeds(self) -> list[ByteUrl] | None:
        """alias to url_list"""
        return self.url_list

    @classmethod
    def read(cls, path: Path | str) -> Self:
        with open(path, "rb") as tfile:
            tdata = tfile.read()
        tdict = bencode_rs.bdecode(tdata)
        return cls.from_decoded(decoded=tdict)

    @classmethod
    def from_decoded(cls, decoded: dict[str | bytes, Any], **data: Any) -> Self:
        """Create from bdecoded dict"""
        if decoded is not None:
            # we fix these incompatible types in str_keys
            decoded.update(data)  # type: ignore
            data = decoded  # type: ignore

        if any([isinstance(k, bytes) for k in data]):
            data = str_keys(data)  # type: ignore
        return cls(**data)

    @property
    def torrent_version(self) -> TorrentVersion:
        if isinstance(self.info, InfoDictV1Base) and not isinstance(self.info, InfoDictV2Base):
            return TorrentVersion.v1
        elif isinstance(self.info, InfoDictV2Base) and not isinstance(self.info, InfoDictV1Base):
            return TorrentVersion.v2
        else:
            return TorrentVersion.hybrid

    @property
    def v1_infohash(self) -> bytes | None:
        return self.info.v1_infohash

    @property
    def v2_infohash(self) -> bytes | None:
        return self.info.v2_infohash

    @property
    def n_files(self) -> int:
        """
        Total number of files described by the torrent, excluding padfiles
        """

        if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
            self.info = cast(InfoDictV1 | InfoDictHybrid, self.info)
            if self.info.files is None:
                return 1
            return len([f for f in self.info.files if f.attr not in (b"p", "p")])
        else:
            self.info = cast(InfoDictV2, self.info)
            tree = FileTree.flatten_tree(self.info.file_tree)
            return len(tree)

    @property
    def total_size(self) -> int:
        """
        Total size of the torrent, excluding padfiles, in bytes
        """
        if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
            self.info = cast(InfoDictV1 | InfoDictHybrid, self.info)
            if self.info.files is None:
                self.info.length = cast(int, self.info.length)
                return self.info.length
            return sum([f.length for f in self.info.files if f.attr not in (b"p", "p")])
        else:
            self.info = cast(InfoDictV2, self.info)
            tree = FileTree.flatten_tree(self.info.file_tree)
            return sum([t["length"] for t in tree.values()])

    @property
    def flat_files(self) -> dict[str, FileTreeItem] | None:
        """A flattened version of the v2 file tree"""
        if self.torrent_version == TorrentVersion.v1:
            return None
        self.info = cast(InfoDictV2, self.info)
        return FileTree.flatten_tree(self.info.file_tree)

    def model_dump_torrent(self, mode: L["str", "binary"] = "binary", **kwargs: Any) -> dict:
        """
        Dump the model into a dictionary that can be bencoded into a torrent

        Args:
            mode ("str", "binary"): ``str`` returns as a 'python' version of the torrent,
                with string keys and serializers applied.
                ``binary`` roundtrips to and from bencoding.
            kwargs: forwarded to :meth:`pydantic.BaseModel.model_dump`
        """
        dumped = self.model_dump(exclude_none=True, by_alias=True, **kwargs)
        if mode == "binary":
            dumped = bencode_rs.bdecode(bencode_rs.bencode(dumped))
        return dumped

    def pprint(self, verbose: int = 0) -> None:
        """
        Pretty print the torrent.

        See :func:`.pprint`
        """
        pprint(self, verbose=verbose)


class Torrent(TorrentBase):
    """
    A valid torrent file, including hashes.
    """

    @model_validator(mode="after")
    def piece_layers_if_v2(self) -> Self:
        """If we are a v2 or hybrid torrent, we should have piece layers"""
        if self.torrent_version in (TorrentVersion.v2, TorrentVersion.hybrid):
            assert self.piece_layers is not None, "Hybrid and v2 torrents must have piece layers"
        return self

    @model_validator(mode="after")
    def pieces_layers_correct(self) -> Self:
        """
        All files with a length longer than the piece length should be in piece layers,
        Piece layers should have the correct number of hashes
        """
        if self.torrent_version == TorrentVersion.v1:
            return self
        self.piece_layers = cast(dict[bytes, bytes], self.piece_layers)
        self.info = cast(InfoDictV2 | InfoDictHybrid, self.info)
        for path, file_info in self.info.flat_tree.items():
            if file_info["length"] > self.info.piece_length:
                assert file_info["pieces root"] in self.piece_layers, (
                    f"file {path} does not have a matching piece root in the piece layers dict. "
                    f"Expected to find: {file_info['pieces root']}"  # type: ignore
                )
                expected_pieces = ceil(file_info["length"] / self.info.piece_length)
                assert len(self.piece_layers[file_info["pieces root"]]) == expected_pieces * 32, (
                    f"File {path} does not have the correct number of piece hashes. "
                    f"Expected {expected_pieces} hashes from file length {file_info['length']} "
                    f"and piece length {self.info.piece_length}. "
                    f"Got {len(self.piece_layers[file_info['pieces root']]) / 32}"
                )
        return self

    def bencode(self) -> bytes:
        dumped = self.model_dump(exclude_none=True, by_alias=True)
        return bencode_rs.bencode(dumped)

    def write(self, path: Path) -> None:
        """Write the torrent to disk"""
        with open(path, "wb") as f:
            f.write(self.bencode())

    @property
    def file_size(self) -> int:
        """Size of the generated torrent file, in bytes"""
        return len(self.bencode())


def pprint(t: TorrentBase, verbose: int = 0) -> None:
    """
    Print the contents of a torrent file.

    By default, prints only the top-level metadata in a way that should always be
    smaller than one screen.

    Increase verbosity to show more of the torrent.

    Hashes are printed as hexadecimal numbers and split into individual pieces,
    but they are properly encoded in the torrent.

    Args:
        t (:class:`.Torrent`): The torrent to print.
        verbose (int): Level of detail to print.

            * ``1`` show files in separate table
            * ``2`` show truncated v1 piece hashes
            * ``3`` show everything as-is

    """
    # summary stats
    summary = {
        "# Files": humanize.number.intcomma(t.n_files),
        "Total Size": humanize.naturalsize(t.total_size, binary=True),
        "Piece Size": humanize.naturalsize(t.info.piece_length, binary=True),
    }
    if hasattr(t, "file_size"):
        summary["Torrent Size"] = humanize.naturalsize(t.file_size, binary=True)

    v1_infohash = t.v1_infohash
    v2_infohash = t.v2_infohash
    if v1_infohash:
        summary["V1 Infohash"] = v1_infohash.hex()
    if v2_infohash:
        summary["V2 Infohash"] = v2_infohash.hex()
    table = Table(title=t.info.name, show_header=False)
    table.add_column("", justify="left", style="magenta bold", no_wrap=True)
    table.add_column("")
    for k, v in summary.items():
        table.add_row(k, v)

    exclude = {}
    context = {"mode": "print", "hash_truncate": True}
    file_table = None
    if verbose <= 1:
        exclude = {"info": {"pieces", "file tree", "file_tree", "files"}, "piece_layers": True}
    elif verbose <= 2:
        exclude = {"info": {"file tree", "file_tree", "files"}, "piece_layers": True}
    else:
        context["hash_truncate"] = False

    # make file table
    if 1 <= verbose <= 2:
        file_table = Table(title="Files")
        file_table.add_column("Path", no_wrap=True)
        file_table.add_column("Size")

        if t.torrent_version == TorrentVersion.v1:
            t.info = cast(InfoDictV1, t.info)
            tfiles = (
                t.info.files
                if t.info.files is not None
                else [FileItem(path=t.info.name, length=t.info.length)]
            )

            files = [
                ("/".join(f.path), humanize.naturalsize(f.length, binary=True), "")
                for f in tfiles
                if f.attr not in (b"p", "p")
            ]
        else:
            t.info = cast(InfoDictV2 | InfoDictHybrid, t.info)
            file_table.add_column("Hash")
            tree = t.flat_files
            assert tree is not None
            files = [
                (
                    str(k),
                    humanize.naturalsize(v["length"], binary=True),
                    v["pieces root"].hex()[0:8],
                )
                for k, v in tree.items()
            ]

        for f in files:
            file_table.add_row(*f)

    dumped = t.model_dump(
        by_alias=True, exclude=exclude, exclude_none=True, context=context  # type: ignore
    )

    if verbose < 1 or verbose > 2:
        group = Group(
            table,
            Pretty(dumped),
        )
    elif verbose <= 2:
        assert file_table is not None
        group = Group(table, file_table, Pretty(dumped))

    print(group)
