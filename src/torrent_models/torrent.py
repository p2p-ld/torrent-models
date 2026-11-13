import posixpath
import warnings
from math import ceil
from pathlib import Path
from typing import Any, BinaryIO, Generic, Self, cast
from typing import Literal as L

import bencode_rs
import humanize
from pydantic import Field, model_validator
from rich import print
from rich.console import Group
from rich.pretty import Pretty
from rich.table import Table

from torrent_models.base import ConfiguredBase
from torrent_models.info import (
    InfoDictHybrid,
    InfoDictV1,
    InfoDictV1Base,
    InfoDictV2,
    InfoDictV2Base,
    InfoT,
)
from torrent_models.layout import FileLayout
from torrent_models.types import (
    ByteStr,
    FileItem,
    FileTreeItem,
    GenericFileItem,
    ListOrValue,
    PieceLayersType,
    TorrentVersion,
    UnixDatetime,
    str_keys,
)
from torrent_models.types.v1 import V1PieceRange
from torrent_models.types.v2 import FileTree, V2PieceRange


class TorrentBase(ConfiguredBase, Generic[InfoT]):  # noqa: UP046 - see InfoT
    announce: ByteStr | None = None
    announce_list: list[list[ByteStr]] | None = Field(default=None, alias="announce-list")
    comment: ByteStr | None = None
    created_by: ByteStr | None = Field(None, alias="created by")
    creation_date: UnixDatetime | None = Field(default=None, alias="creation date")
    info: InfoT
    piece_layers: PieceLayersType | None = Field(None, alias="piece layers")
    url_list: ListOrValue[ByteStr] | None = Field(
        None, alias="url-list", description="List of webseeds"
    )

    _flat_files: dict[str, FileTreeItem] | None = None
    _files: list[GenericFileItem] | None = None

    @property
    def webseeds(self) -> list[str] | None:
        """alias to url_list"""
        return self.url_list

    @classmethod
    def read_stream(cls, stream: BinaryIO, context: dict | None = None) -> Self:
        tdata = stream.read()
        tdict = bencode_rs.bdecode(tdata)
        return cls.from_decoded(decoded=tdict, context=context)

    @classmethod
    def read(cls, path: Path | str, context: dict | None = None) -> Self:
        with open(path, "rb") as tfile:
            torrent = cls.read_stream(tfile, context=context)
        return torrent

    @classmethod
    def from_decoded(
        cls, decoded: dict[str | bytes, Any], context: dict | None = None, **data: Any
    ) -> Self:
        """Create from bdecoded dict"""
        if decoded is not None:
            # we fix these incompatible types in str_keys
            decoded.update(data)  # type: ignore
            data = decoded  # type: ignore

        if any([isinstance(k, bytes) for k in data]):
            data = str_keys(data)  # type: ignore

        if context is None:
            context = {}

        return cls.model_validate(data, context=context)

    @property
    def torrent_version(self) -> TorrentVersion:
        if isinstance(self.info, InfoDictV1Base) and not isinstance(self.info, InfoDictV2Base):
            return TorrentVersion.v1
        elif isinstance(self.info, InfoDictV2Base) and not isinstance(self.info, InfoDictV1Base):
            return TorrentVersion.v2
        else:
            return TorrentVersion.hybrid

    @property
    def v1_infohash(self) -> str | None:
        """hex-encoded SHA1 of the infodict"""
        return self.info.v1_infohash

    @property
    def v2_infohash(self) -> str | None:
        """hex-encoded SHA256 of the infodict"""
        return self.info.v2_infohash

    @property
    def n_files(self) -> int:
        """
        Total number of files described by the torrent, excluding padfiles
        """

        if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
            info = cast(InfoDictV1 | InfoDictHybrid, self.info)
            if info.files is None:
                return 1
            return len([f for f in info.files if not f.is_padfile])
        else:
            info = cast(InfoDictV2, self.info)
            tree = FileTree.flatten_tree(info.file_tree)
            return len(tree)

    @property
    def total_size(self) -> int:
        """
        Total size of the torrent, excluding padfiles, in bytes
        """
        if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
            info = cast(InfoDictV1 | InfoDictHybrid, self.info)
            if info.files is None:
                return cast(int, info.length)
            return sum([f.length for f in info.files if not f.is_padfile])
        else:
            info = cast(InfoDictV2, self.info)
            tree = FileTree.flatten_tree(info.file_tree)
            return sum([t["length"] for t in tree.values()])

    @property
    def flat_files(self) -> dict[str, FileTreeItem] | None:
        """A flattened version of the v2 file tree"""
        if self._flat_files is None and self.torrent_version != TorrentVersion.v1:
            info = cast(InfoDictV2, self.info)
            self._flat_files = FileTree.flatten_tree(info.file_tree)
        return self._flat_files

    @property
    def files(self) -> list[GenericFileItem]:
        """
        Common access to file information from both v1 and v2 torrents
        """
        if self._files is None:
            # v1 and v2 reps already confirmed to be equivalent during validation
            files = []
            if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
                info = cast(InfoDictV1 | InfoDictHybrid, self.info)
                if info.files is None:
                    v1_files = [FileItem(length=info.length, path=[info.name])]
                else:
                    v1_files = info.files
                for f in v1_files:
                    if f.is_padfile:
                        continue
                    v1_repr = f.model_dump()
                    v1_repr["path"] = posixpath.join(*v1_repr["path"])
                    if isinstance(v1_repr["path"], bytes):
                        v1_repr["path"] = v1_repr["path"].decode("utf-8")
                    v1_repr["download_path"] = (
                        v1_repr["path"] if info.files is None else f"{info.name}/{v1_repr['path']}"
                    )
                    if self.torrent_version == TorrentVersion.hybrid:
                        v2_repr = self.flat_files[v1_repr["path"]]  # type: ignore
                    else:
                        v2_repr = {}
                    files.append(GenericFileItem(**{**v1_repr, **v2_repr}))
            else:
                flat_files = cast(dict[str, FileTreeItem], self.flat_files)
                single_file = len(flat_files) == 1
                files = [
                    GenericFileItem(
                        path=k,
                        download_path=k if single_file else f"{self.info.name}/{k}",
                        **v,  # type: ignore[arg-type]
                    )
                    for k, v in flat_files.items()
                ]
            self._files = files
        return self._files

    @property
    def flat_trackers(self) -> list[list[str]]:
        trackers = []
        if self.announce:
            trackers.append([self.announce])
        if self.announce_list:
            trackers.extend(self.announce_list)
        return trackers

    def model_dump_torrent(self, mode: L["str", "binary"] = "str", **kwargs: Any) -> dict:
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


class Torrent(TorrentBase[InfoT]):
    """
    A valid torrent file, including hashes.
    """

    _layout: FileLayout[Any] | None = None

    @property
    def file_size(self) -> int:
        """Size of the generated torrent file, in bytes"""
        return len(self.bencode())

    def bencode(self) -> bytes:
        dumped = self.model_dump_torrent(mode="str")
        return bencode_rs.bencode(dumped)

    def write(self, path: Path) -> None:
        """Write the torrent to disk"""
        with open(path, "wb") as f:
            f.write(self.bencode())

    @property
    def layout(self) -> FileLayout[InfoT]:
        """
        Mapping between files and the pieces that contain their data.

        See: :class:`.FileLayout`
        """
        if self._layout is None:
            self._layout = FileLayout(self)
        return self._layout

    def check(self, root: Path) -> bool:
        """
        Whether all the torrent's data is on disk, and every piece matches its hash.
        ``root`` is the directory the torrent was downloaded to: the one with a directory
        named after the torrent in it, or the file itself if it's the torrent's only file.
        """
        return all(
            self.layout.piece_range(i).validate_data(root) for i in range(self.layout.n_pieces)
        )

    def v1_piece_range(self, piece_idx: int) -> V1PieceRange:
        """Deprecated: use ``torrent.layout.v1_piece_range`` , see :class:`.FileLayout`"""
        warnings.warn(
            "Torrent.v1_piece_range is deprecated, use Torrent.layout.v1_piece_range",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.layout.v1_piece_range(piece_idx)

    def v2_piece_range(self, file: str, piece_idx: int = 0) -> V2PieceRange:
        """Deprecated: use ``torrent.layout.v2_piece_range`` , see :class:`.FileLayout`"""
        warnings.warn(
            "Torrent.v2_piece_range is deprecated, use Torrent.layout.v2_piece_range",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.layout.v2_piece_range(file, piece_idx)

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
        self.piece_layers = cast(PieceLayersType, self.piece_layers)
        info = cast(InfoDictV2 | InfoDictHybrid, self.info)
        for path, file_info in info.flat_tree.items():
            if file_info["length"] > info.piece_length:
                assert file_info["pieces root"] in self.piece_layers, (
                    f"file {path} does not have a matching piece root in the piece layers dict. "
                    f"Expected to find: {file_info['pieces root']}"  # type: ignore
                )
                expected_pieces = ceil(file_info["length"] / info.piece_length)
                assert len(self.piece_layers[file_info["pieces root"]]) == expected_pieces, (
                    f"File {path} does not have the correct number of piece hashes. "
                    f"Expected {expected_pieces} hashes from file length {file_info['length']} "
                    f"and piece length {info.piece_length}. "
                    f"Got {len(self.piece_layers[file_info['pieces root']])}"
                )
        return self


def pprint(t: TorrentBase[Any], verbose: int = 0) -> None:
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
        summary["V1 Infohash"] = v1_infohash
    if v2_infohash:
        summary["V2 Infohash"] = v2_infohash
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
            info = cast(InfoDictV1, t.info)
            tfiles = (
                info.files
                if info.files is not None
                else [FileItem(path=info.name, length=info.length)]
            )

            files = [
                ("/".join(f.path), humanize.naturalsize(f.length, binary=True), "")
                for f in tfiles
                if not f.is_padfile
            ]
        else:
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
