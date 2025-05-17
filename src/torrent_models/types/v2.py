"""
Types used only in v2 (and hybrid) torrents
"""

import multiprocessing as mp
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property
from math import ceil
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NotRequired, TypeAlias, Union, cast
from typing import Literal as L

from anyio import run
from pydantic import AfterValidator, BaseModel, PlainSerializer
from pydantic_core.core_schema import SerializationInfo
from tqdm.asyncio import tqdm
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
PieceLayersType = dict[PieceLayerItem, PieceLayerItem]
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

    These are separated because the padding added to the

    References:
        - https://www.bittorrent.org/beps/bep_0052_torrent_creator.py
    """

    path: AbsPath | None = None
    """Absolute path to file on filesystem"""
    torrent_path: RelPath | None = None
    """Path within torrent file"""
    piece_length: int
    """Piece length, in bytes"""
    piece_hashes: list[SHA256Hash]
    """hashes of each piece (the nth later of the merkle tree, determined by piece length)"""
    root_hash: bytes
    """Root hash of the tree"""

    leaf_hashes: list[SHA256Hash] | None = None
    """SHA256 hashes of 16KiB leaf segments, if present."""

    @classmethod
    def from_path(
        cls,
        path: Path,
        piece_length: int,
        n_processes: int = mp.cpu_count(),
        progress: bool = False,
        pool: PoolType | None = None,
    ) -> "MerkleTree":
        """
        Create a MerkleTree and return it with computed hashes
        """
        tree = MerkleTree(
            path=path,
            piece_length=piece_length,
            n_processes=n_processes,
            progress=progress,
        )
        _ = run(tree.hash_file, pool)
        return tree


class MerkleTreeShape(BaseModel):
    """
    Helper class to calculate values when constructing a merkle tree,
    without needing to have a merkle tree itself.

    Separated so that :class:`.MerkleTree` could just be a validated representation of the merkle tree
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
        else:
            return self.blocks_per_piece - (self.n_blocks % self.blocks_per_piece)

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

    ```
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
    ```
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
    def from_trees(cls, trees: list[MerkleTree], base_path: Path | None = None) -> "FileTree":
        flat = {}
        for tree in trees:
            if tree.torrent_path:
                # tree already knows its relative directory, use that
                rel_path = tree.torrent_path
            else:
                if base_path is None:
                    raise ValueError(
                        f"Merkle tree for {tree.path} does not have a torrent_path set,"
                        f"and no base_path was provided."
                        f"Unsure what relative path should go in a torrent file."
                    )
                rel_path = tree.path.relative_to(base_path)
            tree.root_hash = cast(bytes, tree.root_hash)
            flat[rel_path.as_posix()] = FileTreeItem(
                **{"pieces root": tree.root_hash, "length": get_size(tree.path)}
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
    piece_layers: dict[bytes, bytes]
    """piece layers: mapping from root hash to concatenated piece hashes"""
    file_tree: FileTree

    @classmethod
    def from_trees(
        cls, trees: list[MerkleTree] | MerkleTree, base_path: Path | None = None
    ) -> "PieceLayers":
        if not isinstance(trees, list):
            trees = [trees]
        lengths = [t.piece_length for t in trees]
        assert all(
            [lengths[0] == ln for ln in lengths]
        ), "Differing piece lengths in supplied merkle trees!"
        piece_length = lengths[0]
        piece_layers = {
            tree.root_hash: b"".join(tree.piece_hashes)
            for tree in trees
            if tree.piece_hashes and tree.root_hash is not None
        }
        file_tree = FileTree.from_trees(trees)
        return PieceLayers(
            piece_length=piece_length, piece_layers=piece_layers, file_tree=file_tree
        )

    @classmethod
    def from_paths(
        cls,
        paths: list[Path],
        piece_length: int,
        path_root: Path | None = None,
        n_processes: int = mp.cpu_count(),
        progress: bool = False,
    ) -> "PieceLayers":
        """
        Hash all the paths, construct the piece layers and file tree
        """
        from torrent_models.hashing.base import DummyPbar, PbarLike

        if path_root is None:
            path_root = Path.cwd()

        file_pbar: PbarLike
        if progress:
            file_pbar = tqdm(total=len(paths), desc="Hashing files...", position=0)
        else:
            file_pbar = DummyPbar()

        piece_layers = {}
        file_tree = {}
        pool = mp.Pool(processes=n_processes)
        for path in paths:
            file_pbar.set_description(f"Hashing {path}")
            if path.is_absolute():
                raise ValueError(
                    f"Got absolute path {path}, "
                    f"paths must be relative unless you want to put the whole filesystem "
                    f"in a torrent. (don't put the whole filesystem in a torrent)."
                )
            abs_path = path_root / path
            tree = MerkleTree.from_path(
                path=abs_path, piece_length=piece_length, pool=pool, progress=progress
            )
            tree.root_hash = cast(bytes, tree.root_hash)
            file_tree[path.as_posix()] = FileTreeItem(
                **{"pieces root": tree.root_hash, "length": get_size(abs_path)}
            )
            if tree.piece_hashes:
                piece_layers[tree.root_hash] = b"".join(tree.piece_hashes)
            file_pbar.update()

        file_tree = FileTree.from_flat(file_tree)
        piece_layers = piece_layers

        file_pbar.close()
        pool.close()
        return PieceLayers(
            piece_length=piece_length,
            file_tree=file_tree,
            piece_layers=piece_layers,
        )
