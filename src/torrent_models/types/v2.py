"""
Types used only in v2 (and hybrid) torrents
"""

import multiprocessing as mp
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NotRequired, TypeAlias, Union, cast
from typing import Literal as L

from pydantic import AfterValidator, BaseModel, PlainSerializer
from pydantic_core.core_schema import SerializationInfo
from typing_extensions import TypeAliasType, TypedDict

from torrent_models.compat import get_size
from torrent_models.const import BLOCK_SIZE
from torrent_models.types.common import (
    AbsPath,
    RelPath,
    SHA256Hash,
    _divisible_by_16kib,
    _power_of_two,
)

if TYPE_CHECKING:
    pass

V2PieceLength = Annotated[int, AfterValidator(_divisible_by_16kib), AfterValidator(_power_of_two)]
"""
Per BEP 52: "must be a power of two and at least 16KiB"
"""


def _serialize_v2_hash(value: bytes, info: SerializationInfo) -> bytes | str | list[str]:
    if info.context and info.context.get("mode") == "print":
        ret: str = value.hex()

        if info.context.get("hash_truncate"):
            ret = ret[0:8]
        # split layers
        if len(ret) > 64:
            return [ret[i : i + 64] for i in range(0, len(ret), 64)]
        else:
            return ret

    return value


PieceLayerItem = Annotated[bytes, PlainSerializer(_serialize_v2_hash)]
PieceLayersType = dict[SHA256Hash, PieceLayerItem]
FileTreeItem = TypedDict(
    "FileTreeItem", {"length": int, "pieces root": NotRequired[PieceLayerItem]}
)
FileTreeType: TypeAlias = TypeAliasType(  # type: ignore
    "FileTreeType", dict[bytes, Union[dict[L[""], FileTreeItem], "FileTreeType"]]  # type: ignore
)


class MerkleTree(BaseModel):
    """
    Representation and computation of v2 merkle trees

    A v2 merkle tree is a branching factor 2 tree where each of the leaf nodes is a 16KiB block.

    Two layers of the tree are embedded in a torrent file:

    - the ``piece layer``: the hashes from ``piece length/16KiB`` layers from the leaves.
      or, the layer where each hash corresponds to a chunk of the file ``piece length`` long.
    - the tree root.

    Padding is performed in two steps:

    - For files whose size is not a multiple of ``piece length``,
      pad the *leaf hashes* with zeros
      (the hashes, not the leaf data, i.e. 32 bytes not 16KiB of zeros)
      such that there are enough blocks to complete a piece
    - For files there the number of pieces does not create a balanced merkle tree,
      pad the *pieces hashes* with identical piece hashes each ``piece length`` long
      s.t. their leaf hashes are all zeros, as above.

    These are separated to avoid computing hashes of zero's unnecessarily.

    References:
        - https://www.bittorrent.org/beps/bep_0052_torrent_creator.py
    """

    path: RelPath
    """Path within torrent file"""
    piece_length: int
    """Piece length, in bytes"""
    piece_hashes: list[SHA256Hash] | None
    """
    hashes of each piece (the nth later of the merkle tree, determined by piece length).
    
    When a file is smaller than a single piece, set explicitly to ``None``.
    """
    root_hash: bytes
    """Root hash of the tree"""

    leaf_hashes: list[SHA256Hash] | None = None
    """SHA256 hashes of 16KiB leaf segments, if present."""

    @classmethod
    def from_path(
        cls,
        path: Path,
        piece_length: V2PieceLength,
        path_root: AbsPath | None = None,
        n_processes: int = mp.cpu_count(),
        progress: bool = False,
        **kwargs: Any,
    ) -> "MerkleTree":
        """
        Create a MerkleTree and return it with computed hashes

        Args:
            path (Path): Relative path to a file within a torrent directory. If absolute,
                must be beneath ``path_root``
            piece_length (V2PieceLength): Piece length used for piece hashes
            path_root (Path): Absolute path that should serve as the root of the torrent,
                the `path` must be a relative or absolute path within it.
            n_processes (int): Number of processes to use while hashing,
                default is n_cpus
            progress (bool): Display progress while hashing
            kwargs: Passed to :class:`.V2Hasher`

        """
        from torrent_models.hashing.v2 import V2Hasher

        if path_root is None:
            path_root = path.parent.resolve()
        else:
            assert path_root.is_absolute(), "Path root must be absolute"

        if path.is_absolute():
            path = path.relative_to(path_root)

        hasher = V2Hasher(
            paths=[path],
            piece_length=piece_length,
            path_root=path_root,
            n_processes=n_processes,
            progress=progress,
            **kwargs,
        )
        hashes = hasher.process()
        trees = hasher.finish_trees(hashes)
        assert len(trees) == 1, "Multiple trees returned from a single file constructor!"
        return trees[0]


class MerkleTreeShape(BaseModel):
    """
    Helper class to calculate values when constructing a merkle tree,
    without needing to have a merkle tree itself.

    Separated so that :class:`.MerkleTree` could just be a
    validated representation of the merkle tree
    rather than being the thing that hashes one,
    while also being able to validate the tree.
    """

    file_size: int
    """size of the file for which the merkle tree would be calculated, in bytes"""
    piece_length: V2PieceLength
    """piece length of the merkle tree"""

    @property
    def blocks_per_piece(self) -> int:
        return self.piece_length // BLOCK_SIZE

    @cached_property
    def n_blocks(self) -> int:
        """Number of total blocks in the file (excluding padding blocks)"""
        return ceil(self.file_size / BLOCK_SIZE)

    @cached_property
    def n_pieces(self) -> int:
        """Number of pieces in the file (or 0, if file is < piece_length)"""
        n_pieces = self.file_size / self.piece_length
        if n_pieces < 1:
            return 0
        else:
            return ceil(n_pieces)

    @cached_property
    def n_pad_blocks(self) -> int:
        """
        Number of blank blocks required for padding when hashing.

        Not strictly equivalent to the remainder to the nearest piece size,
        because we skip hashing all the zero blocks when we don't need to.
        (e.g. when to balance the tree we need to compute a ton of empty piece hashes)
        """
        if self.n_pieces <= 1:
            total_blocks = 1 << (self.n_blocks - 1).bit_length()
            return total_blocks - self.n_blocks
        elif (remainder := self.n_blocks % self.blocks_per_piece) == 0:
            return 0
        else:
            return self.blocks_per_piece - remainder

    @cached_property
    def n_pad_pieces(self) -> int:
        """Number of blank pieces required to balance merkle tree"""
        if self.n_pieces < 1:
            return 0
        return (1 << (self.n_pieces - 1).bit_length()) - self.n_pieces

    def validate_leaf_count(self, n_leaf_hashes: int) -> None:
        """Ensure that we have the right number of leaves for a merkle tree"""
        if self.n_pieces == 0:
            # ensure that n_blocks is a power of two
            n = n_leaf_hashes
            assert (n & (n - 1) == 0) and n != 0, (
                "For files smaller than one piece, "
                "must pad number of leaf blocks with zero blocks so n leaves is a power of two. "
                f"Got {n_leaf_hashes} leaf hashes with blocks_per_piece {self.blocks_per_piece}"
            )
        else:
            assert n_leaf_hashes % self.blocks_per_piece == 0, (
                f"leaf hashes must be a multiple of blocks per piece, pad with zeros. "
                f"Got {n_leaf_hashes} leaf hashes with blocks_per_piece {self.blocks_per_piece}"
            )


class FileTree(BaseModel):
    """
    A v2 torrent file tree is like

    - `folder/file1.png`
    - `file2.png`

    .. code-block:: python

        {
            "folder": {
                "file1.png": {
                    "": {
                        "length": 123,
                        "pieces root": b"<hash>",
                    }
                }
            },
            "file2.png": {
                "": {
                    "length": 123,
                    "pieces root": b"<hash>",
                }
            }
        }

    """

    tree: FileTreeType

    @classmethod
    def flatten_tree(cls, tree: FileTreeType) -> dict[str, FileTreeItem]:
        """
        Flatten a file tree, mapping each path to the item description
        """
        return _flatten_tree(tree)

    @classmethod
    def unflatten_tree(cls, tree: dict[str, FileTreeItem]) -> FileTreeType:
        """
        Turn a flattened file tree back into a nested file tree
        """
        return _unflatten_tree(tree)

    @cached_property
    def flat(self) -> dict[str, FileTreeItem]:
        """Flattened FileTree"""
        return self.flatten_tree(self.tree)

    @classmethod
    def from_flat(cls, tree: dict[str, FileTreeItem]) -> "FileTree":
        return cls(tree=cls.unflatten_tree(tree))

    @classmethod
    def from_trees(cls, trees: list[MerkleTree], base_path: Path) -> "FileTree":
        flat = {}
        for tree in trees:
            flat[tree.path.as_posix()] = FileTreeItem(
                **{"pieces root": tree.root_hash, "length": get_size(base_path / tree.path)}
            )
        return cls.from_flat(flat)


def _flatten_tree(val: dict, parts: list[str] | list[bytes] | None = None) -> dict:
    # NOT a general purpose dictionary walker.
    out: dict[bytes | str, dict] = {}
    if parts is None:
        # top-level, copy the input value
        val = deepcopy(val)
        parts = []

    for k, v in val.items():
        if isinstance(k, bytes):
            k = k.decode("utf-8")
        if k in (b"", ""):
            if isinstance(k, bytes):
                parts = cast(list[bytes], parts)
                out[b"/".join(parts)] = v
            elif isinstance(k, str):
                parts = cast(list[str], parts)
                out["/".join(parts)] = v
        else:
            out.update(_flatten_tree(v, parts + [k]))
    return out


def _unflatten_tree(val: dict) -> dict:
    out: dict[str | bytes, dict] = {}
    for k, v in val.items():
        is_bytes = isinstance(k, bytes)
        if is_bytes:
            k = k.decode("utf-8")
        parts = k.split(b"/") if is_bytes else k.split("/")
        parts = [p for p in parts if p not in (b"", "")]
        nested_subdict = out
        for part in parts:
            if part not in nested_subdict:
                nested_subdict[part] = {}
                nested_subdict = nested_subdict[part]
            else:
                nested_subdict = nested_subdict[part]
        if is_bytes:
            nested_subdict[b""] = v
        else:
            nested_subdict[""] = v
    return out


@dataclass
class PieceLayers:
    """
    Constructor for piece layers, along with the file tree, from a list of files

    Constructed together since file tree is basically a mapping of paths to root hashes -
    they are joint objects
    """

    piece_length: int
    """piece length (hash piece_length/16KiB blocks per piece hash)"""
    piece_layers: PieceLayersType
    """piece layers: mapping from root hash to concatenated piece hashes"""
    file_tree: FileTree

    @classmethod
    def from_trees(cls, trees: list[MerkleTree] | MerkleTree, base_path: Path) -> "PieceLayers":
        if not isinstance(trees, list):
            trees = [trees]
        lengths = [t.piece_length for t in trees]
        assert all(
            [lengths[0] == ln for ln in lengths]
        ), "Differing piece lengths in supplied merkle trees!"
        piece_length = lengths[0]
        piece_layers = {
            tree.root_hash: b"".join(tree.piece_hashes) for tree in trees if tree.piece_hashes
        }
        file_tree = FileTree.from_trees(trees, base_path)
        return PieceLayers(
            piece_length=piece_length, piece_layers=piece_layers, file_tree=file_tree
        )

    @classmethod
    def from_paths(
        cls,
        paths: list[RelPath],
        piece_length: int,
        path_root: Path,
        n_processes: int = mp.cpu_count(),
        progress: bool = False,
        **kwargs: Any,
    ) -> "PieceLayers":
        """
        Hash all the paths, construct the piece layers and file tree

        Args:
            paths (list[Path]): List of relative paths within some path root
            piece_length (V2PieceLength): piece length valid for v2 torrents
            path_root (Path): Root directory that contains ``paths``
            n_processes (int): number of processes to use for parallel processing.
                Default is n_cpus
            progress (bool): Display progress while hashing
            kwargs: passed to :class:`.V2Hasher`

        """
        from torrent_models.hashing.v2 import V2Hasher

        hasher = V2Hasher(
            paths=paths,
            path_root=path_root,
            piece_length=piece_length,
            n_processes=n_processes,
            progress=progress,
            **kwargs,
        )
        hashes = hasher.process()
        trees = hasher.finish_trees(hashes)
        return cls.from_trees(trees, base_path=path_root)
