import multiprocessing as mp
from math import ceil
from pathlib import Path
from typing import Any, Self, cast
from typing import Literal as L

import bencode_rs
from pydantic import (
    Field,
    model_validator,
)

from torrent_models.base import ConfiguredBase
from torrent_models.const import EXCLUDE_FILES
from torrent_models.hashing.hybrid import HybridHasher, add_padfiles
from torrent_models.hashing.v1 import hash_pieces
from torrent_models.hashing.v2 import FileTree, PieceLayers
from torrent_models.info import (
    InfoDictHybrid,
    InfoDictHybridCreate,
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
    V1PieceLength,
    V2PieceLength,
    str_keys,
)


class TorrentBase(ConfiguredBase):
    announce: ByteUrl
    announce_list: list[list[ByteUrl]] | None = Field(default=None, alias="announce-list")
    comment: ByteStr | None = None
    created_by: ByteStr | None = Field(None, alias="created by")
    creation_date: UnixDatetime | None = Field(default=None, alias="creation date")
    info: InfoDictV1 | InfoDictV2 | InfoDictHybrid = Field(..., union_mode="left_to_right")
    piece_layers: PieceLayersType | None = Field(None, alias="piece layers")
    webseeds: ListOrValue[ByteUrl] | None = Field(None, alias="url-list")

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
            if self.info.files is None:
                return 1
            return len([f for f in self.info.files if f.attr not in (b"p", "p")])
        else:
            tree = FileTree.flatten_tree(self.info.file_tree)
            return len(tree)

    @property
    def total_size(self) -> int:
        """
        Total size of the torrent, excluding padfiles, in bytes
        """
        if self.torrent_version in (TorrentVersion.v1, TorrentVersion.hybrid):
            if self.info.files is None:
                return self.info.length
            return sum([f.length for f in self.info.files if f.attr not in (b"p", "p")])
        else:
            tree = FileTree.flatten_tree(self.info.file_tree)
            return sum([t["length"] for t in tree.values()])

    @property
    def flat_files(self) -> dict[str, FileTreeItem] | None:
        """A flattened version of the v2 file tree"""
        if self.torrent_version == TorrentVersion.v1:
            return None
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


class TorrentCreate(TorrentBase):
    """
    A programmatically created torrent that may not have its hashes computed yet.

    Torrents may be created *either* by passing an info dict with all details,
    (with or without piece hashes), *or* by using a handful of convenience fields.
    E.g. rather than needing to pass a fully instantiated file tree,
    one can just pass a list of files to ``files``
    """

    _EXCLUDE = {
        "paths": True,
        "path_root": True,
        "trackers": True,
        "piece_length": True,
        "info": {"meta_version", "files", "file_tree", "piece_length"},
        "piece_layers": True,
    }
    """
    Exclude from model dumps when creating internal model dumps when generating.
    ie. because they are transformed by creation
    """

    # make parent types optional
    announce: ByteUrl | None = None  # type: ignore

    # convenience fields
    info: InfoDictHybridCreate = Field(default_factory=InfoDictHybridCreate)  # type: ignore
    paths: list[Path] | None = Field(
        None,
        description="""
        Convenience field for creating torrents from lists of files.
        Can be either relative or absolute.
        Paths must be located beneath the path root, passed either explicitly or using
        cwd (default).
        If absolute, paths are made relative to the path root.
        """,
    )
    path_root: Path = Field(default_factory=Path, description="Path to interpret paths relative to")

    trackers: list[ByteUrl] | list[list[ByteUrl]] | None = Field(
        None,
        description="Convenience method for declaring tracker lists."
        "If a flat list, put each tracker in a separate tier."
        "Otherwise, sublists indicate tiers.",
    )
    piece_length: V1PieceLength | V2PieceLength | None = Field(
        None, description="Convenience method for passing piece length"
    )
    similar: list[bytes] | None = Field(
        None, description="Infohashes of other torrents that might contain overlapping files"
    )

    @model_validator(mode="after")
    def files_xor_info_files(self) -> Self:
        """Can only specify convenience file field or fill the file field in the infodict"""
        files_in_info = self.info.files is not None or self.info.length is not None
        assert (
            bool(self.paths) or files_in_info
        ), "Must specify files either in `paths` or in `info`"
        assert (
            bool(self.paths) != files_in_info
        ), "Can only pass the top-level files field OR the files list/length in the infodict"
        return self

    @model_validator(mode="after")
    def no_duplicated_params(self) -> Self:
        """
        Ensure that values that can be set from the top level convenience fields aren't doubly set,

        We don't set the accompanying values in the infodict on instantiation because
        this object is intended to be a programmatic constructor object,
        so we expect these values to change and don't want to have to worry about
        state consistency in it -
        all values are gathered and validated when the torrent is generated.
        """
        if self.paths:
            assert not self.info.files, "Can't pass both paths and info.files"
            assert not self.info.file_tree, "Can't pass both paths and info.file_tree"
        if self.trackers:
            assert not self.announce, "Can't pass both trackers and announce"
            assert not self.announce_list, "Can't pass both trackers and announce_list"
        if self.piece_length:
            assert not self.info.piece_length, "Can't pass both piece_length and info.piece_length"
        return self

    @model_validator(mode="after")
    def name_from_path_root(self) -> Self:
        """If `name` is not provided, infer it from the path root"""
        if not self.info.name:
            self.info.name = self.path_root.name
        return self

    def generate(
        self, version: TorrentVersion | str, n_processes: int | None = None, progress: bool = False
    ) -> Torrent:
        """
        Generate a torrent file, hashing its pieces and transforming convenience values
        to valid torrent values.
        """
        if isinstance(version, str):
            version = TorrentVersion.__members__[version]

        if n_processes is None:
            n_processes = mp.cpu_count()

        if version == TorrentVersion.v1:
            return self._generate_v1(n_processes, progress)
        elif version == TorrentVersion.v2:
            return self._generate_v2(n_processes, progress)
        elif version == TorrentVersion.hybrid:
            return self._generate_hybrid(n_processes, progress)
        else:
            raise ValueError(f"Unknown torrent version: {version}")

    def generate_libtorrent(
        self,
        version: TorrentVersion | str,
        output: Path | None = None,
        bencode: bool = False,
        progress: bool = False,
    ) -> dict | bytes:
        from torrent_models.libtorrent import create_from_model

        return create_from_model(
            self, version=version, progress=progress, output=output, bencode=bencode
        )

    def _generate_common(self) -> dict:
        # dump just the fields we want to have in the final torrent,
        # excluding top-level convenience fields (set in the generate methods),
        # and hash values which are created during generation
        dumped = self.model_dump(
            exclude_none=True,
            exclude=self._EXCLUDE,
            by_alias=False,
        )

        dumped["info"]["piece_length"] = self._get_piece_length()
        if "similar" in dumped:
            dumped["info"]["similar"] = dumped["similar"]
            del dumped["similar"]
        dumped.update(self.get_trackers())
        return dumped

    def _generate_v1(self, n_processes: int | None = None, progress: bool = False) -> Torrent:
        dumped = self._generate_common()

        file_items, files = self._get_v1_paths(v1_only=True)

        if not self.info.files:
            dumped["info"]["files"] = file_items

        if "pieces" not in dumped["info"]:
            dumped["info"]["pieces"] = hash_pieces(
                files,
                piece_length=dumped["info"]["piece_length"],
                path_root=self.path_root,
                sort=False,
                progress=progress,
                n_processes=n_processes,
            )

        info = InfoDictV1(**dumped["info"])
        del dumped["info"]
        return Torrent(info=info, **dumped)

    def _generate_v2(self, n_processes: int | None = None, progress: bool = False) -> Torrent:
        dumped = self._generate_common()
        if self.paths:
            paths = clean_files(self.paths, relative_to=self.path_root)
        else:
            # remake with new hashes
            # paths within the file tree should already be relative, no need to fix them
            paths = [path for path in FileTree.flatten_tree(self.info.file_tree)]

        if "piece_layers" not in dumped or "file_tree" not in dumped["info"]:
            piece_layers = PieceLayers.from_paths(
                paths=paths,
                piece_length=dumped["info"]["piece_length"],
                path_root=self.path_root,
                n_processes=n_processes,
                progress=progress,
            )
            dumped["piece_layers"] = piece_layers.piece_layers
            dumped["info"]["file_tree"] = piece_layers.file_tree.tree

        info = InfoDictV2(**dumped["info"])
        del dumped["info"]
        return Torrent(info=info, **dumped)

    def _generate_hybrid(self, n_processes: int | None = None, progress: bool = False) -> Torrent:
        dumped = self._generate_common()

        # Gather paths
        if self.paths:
            paths = clean_files(self.paths, relative_to=self.path_root)
            v1_items, _ = self._get_v1_paths(paths)
        elif (self.info.files or self.info.length) and self.info.file_tree:
            # check for inconsistent paths in v1 and v2 if both are present
            v1_items, v1_paths = self._get_v1_paths()
            v2_paths = [Path(path) for path in FileTree.flatten_tree(self.info.file_tree)]
            if not len(v1_paths) == len(v2_paths) and not all(
                [v1p == v2p for v1p, v2p in zip(v1_paths, v2_paths)]
            ):
                raise ValueError(
                    "Both v1 files and v2 file tree present, but have inconsistent paths!"
                )
            paths = v2_paths
        elif self.info.files or self.info.length:
            # v1 files
            v1_items, paths = self._get_v1_paths()
        elif self.info.file_tree:
            # v2 file tree
            paths = [Path(path) for path in FileTree.flatten_tree(self.info.file_tree)]
            v1_items, _ = self._get_v1_paths(paths)
        else:
            raise ValueError(
                ".paths, v1 paths, and v2 paths were not specified! " "nothing in this torrent!"
            )

        # add padding to the v1 files
        v1_items = add_padfiles(v1_items, dumped["info"]["piece_length"])

        hasher = HybridHasher(
            paths=paths,
            path_base=self.path_root,
            piece_length=self.piece_length,
            n_processes=n_processes,
            progress=progress,
        )
        piece_layers, v1_pieces = hasher.process()
        dumped["piece layers"] = piece_layers.piece_layers
        dumped["info"]["file tree"] = piece_layers.file_tree.tree
        dumped["info"]["pieces"] = v1_pieces
        if len(v1_items) == 1:
            dumped["info"]["name"] = v1_items[0].path
            dumped["info"]["length"] = v1_items[0].length
        else:
            dumped["info"]["files"] = v1_items

        info = InfoDictHybrid(**dumped["info"])
        del dumped["info"]
        return Torrent(info=info, **dumped)

    def get_paths(self, clean: bool = True, v1_order: bool = False) -> list[Path]:
        """
        Get paths specified in one of potentially several ways

        In order (first match is returned):
        - paths set in top level `paths` field
        - v2 file tree, if present
        - v1 `files`, if present
        - v1 `name`, otherwise

        Args:
            clean (bool): clean and sort the files
            v1_order (bool): sort files in v1 order -
                first top-level files, then files in directories
                in case-sensitive alphanumeric order within those categories.
        """
        if self.paths:
            paths = self.paths.copy()
        elif self.info.file_tree:
            tree = self.flat_files
            paths = [Path(t) for t in tree]
        else:
            _, paths = self._get_v1_paths()
            return paths

        if clean:
            paths = clean_files(paths, relative_to=self.path_root, v1=v1_order)
        return paths

    def _get_v1_paths(
        self, paths: list[Path] | None = None, v1_only: bool = False
    ) -> tuple[list[FileItem], list[Path]]:
        if paths:
            files = paths
        elif self.paths:
            files = self.paths
        elif self.info.files:
            files = [Path(*f.path) for f in cast(list[FileItem], self.info.files)]
        elif self.info.length:
            files = [Path(self.info.name)]
        else:
            raise ValueError("paths not provided, and info.files and info.length are unset!")

        files = clean_files(files, relative_to=self.path_root, v1=v1_only)

        items = [
            FileItem(path=list(f.parts), length=(self.path_root / f).stat().st_size) for f in files
        ]
        return items, files

    def get_trackers(
        self,
    ) -> dict[L["announce"] | L["announce-list"], ByteUrl | list[list[ByteUrl]]]:
        # FIXME: hideous
        if self.trackers:
            if isinstance(self.trackers[0], list):
                if len(self.trackers[0]) == 1 and len(self.trackers[0][0]) == 1:
                    return {"announce": self.trackers[0][0]}
                else:
                    return {"announce": self.trackers[0][0], "announce-list": self.trackers}
            else:
                if len(self.trackers) == 1:
                    return {"announce": self.trackers[0]}
                else:
                    self.trackers = cast(list[ByteUrl], self.trackers)
                    return {
                        "announce": self.trackers[0],
                        "announce-list": [[t] for t in self.trackers],
                    }
        else:
            trackers: dict[L["announce"] | L["announce-list"], ByteUrl | list[list[ByteUrl]]] = {}
            if self.announce:
                trackers["announce"] = str(self.announce)
            if self.announce_list:
                trackers["announce-list"] = self.announce_list
            return trackers

    def _get_piece_length(self) -> int:
        piece_length = self.piece_length if self.piece_length else self.info.piece_length
        if piece_length is None:
            raise ValueError("No piece length provided!")
        return piece_length


def list_files(path: Path | str) -> list[Path]:
    """
    Recursively list files relative to path, sorting, excluding known system files
    """
    path = Path(path)
    if path.is_file():
        return [path]

    paths = list(path.rglob("*"))

    return clean_files(paths, path)


def sort_v1(paths: list[Path]) -> list[Path]:
    """
    v1 sorts top-level files first, then within that division alphabetically
    https://github.com/alanmcgovern/monotorrent/issues/563
    """
    return sorted(paths, key=lambda path: (len(path.parts) != 1, str(path).lower()))


def clean_files(paths: list[Path], relative_to: Path, v1: bool = False) -> list[Path]:
    """
    Remove system files, and make paths relative to some directory root
    """
    cleaned = []
    for f in paths:
        if f.is_absolute():
            abs_f = f
            # no absolute paths in the torrent plz
            rel_f = f.relative_to(relative_to)
        else:
            abs_f = relative_to / f
            rel_f = f
        if abs_f.is_file() and f.name not in EXCLUDE_FILES:
            cleaned.append(rel_f)
    cleaned = sort_v1(cleaned) if v1 else sorted(cleaned, key=lambda f: f.as_posix())
    return cleaned
