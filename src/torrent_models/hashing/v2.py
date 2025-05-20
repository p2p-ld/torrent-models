import hashlib
from collections import defaultdict
from functools import cached_property
from itertools import count
from multiprocessing.pool import AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path

from pydantic import PrivateAttr, field_validator

from torrent_models.compat import get_size
from torrent_models.const import BLOCK_SIZE
from torrent_models.hashing.base import Chunk, Hash, HasherBase
from torrent_models.types import SHA256Hash
from torrent_models.types.v2 import MerkleTree, MerkleTreeShape, V2PieceLength


class V2Hasher(HasherBase):
    piece_length: V2PieceLength
    read_size: V2PieceLength | None = None

    _v2_counter: count = PrivateAttr(default_factory=count)

    @classmethod
    @field_validator("read_size", mode="after")
    def read_size_is_block_size(cls, value: int) -> int:
        assert value == BLOCK_SIZE
        return value

    def _update_v2(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        chunks = [
            Chunk.model_construct(
                path=chunk.path, chunk=chunk.chunk[i : i + BLOCK_SIZE], idx=next(self._v2_counter)
            )
            for i in range(0, len(chunk.chunk), BLOCK_SIZE)
        ]
        return [pool.apply_async(self._hash_v2, (c, self.path_root)) for c in chunks]

    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        return self._update_v2(chunk, pool)

    @cached_property
    def total_hashes(self) -> int:
        return self._v2_total_hashes()

    @classmethod
    def hash_root(
        cls,
        hashes: list[SHA256Hash],
    ) -> bytes:
        """
        Given hashes within a v2 merkle tree, compute their root.

        References:
            - https://www.bittorrent.org/beps/bep_0052_torrent_creator.py
        """
        assert len(hashes) & (len(hashes) - 1) == 0, "Must pass a balanced number of pieces"

        while len(hashes) > 1:
            hashes = [
                hashlib.sha256(left + right).digest() for left, right in zip(*[iter(hashes)] * 2)
            ]
        return hashes[0]

    def finish_trees(self, hashes: list["Hash"]) -> list["MerkleTree"]:
        """
        Create from a collection of leaf hashes.

        If leaf hashes from multiple paths are found, return a list of merkle trees.

        This method does *not* check that the trees are correct and complete -
        it assumes that the collection of leaf hashes passed to it is already complete.
        So e.g. it does not validate that the number of leaf hashes matches that which
        would be expected given the file size.

        Args:
            hashes (list[Hash]): collection of leaf hashes, from a single or multiple files
        """

        leaf_hashes = [h for h in hashes if h.type == "block"]
        leaf_hashes = sorted(leaf_hashes, key=lambda h: (h.path, h.idx))
        file_hashes = defaultdict(list)
        for h in leaf_hashes:
            file_hashes[h.path].append(h)

        trees = []
        for path, hashes in file_hashes.items():
            file_size = get_size(self.path_root / path)
            shape = MerkleTreeShape(file_size=file_size, piece_length=self.piece_length)
            hash_bytes = [h.hash for h in hashes]
            if len(hash_bytes) < shape.n_blocks + shape.n_pad_blocks:
                hash_bytes += [bytes(32)] * shape.n_pad_blocks

            piece_hashes = self.hash_pieces(hash_bytes, shape)
            if piece_hashes is None:
                root_hash = self.get_root_hash(hash_bytes, shape)
            else:
                root_hash = self.get_root_hash(piece_hashes, shape)

            tree = MerkleTree(
                path=path,
                piece_length=self.piece_length,
                leaf_hashes=hash_bytes,
                piece_hashes=piece_hashes,
                root_hash=root_hash,
            )
            trees.append(tree)
        return trees

    def hash_pieces(
        self, leaf_hashes: list[SHA256Hash], shape: MerkleTreeShape
    ) -> list[bytes] | None:
        """Compute the piece hashes for the layer dict"""
        if shape.n_pieces <= 1:
            return None

        shape.validate_leaf_count(len(leaf_hashes))
        # with concurrent.futures.ProcessPoolExecutor(max_workers=self.n_processes) as executor:
        piece_hashes = [
            self.hash_root(leaf_hashes[idx : idx + shape.blocks_per_piece])
            for idx in range(0, len(leaf_hashes), shape.blocks_per_piece)
        ]
        return piece_hashes

    def get_root_hash(self, piece_hashes: list[SHA256Hash], shape: MerkleTreeShape) -> bytes:
        """
        Compute the root hash, including any zero-padding pieces needed to balance the tree.

        If n_pieces == 0, the root hash is just the hash tree of the blocks,
        padded with all-zero blocks to have enough blocks for a full piece.

        So if `shape.n_pieces == 0`, then the hashes passed in should be the
        *leaf hashes* (since there are no piece hashes)
        """
        if shape.n_pieces <= 1:
            return self.hash_root(piece_hashes)

        if len(piece_hashes) == 1:
            return piece_hashes[0]

        if len(piece_hashes) == shape.n_pieces and shape.n_pad_pieces > 0:
            pad_piece_hash = self.hash_root([bytes(32)] * shape.blocks_per_piece)
            piece_hashes = piece_hashes + ([pad_piece_hash] * shape.n_pad_pieces)
        elif len(piece_hashes) != shape.n_pieces + shape.n_pad_pieces:
            raise ValueError(
                f"Expected either {shape.n_pieces} (unpadded) piece hashes or "
                f"{shape.n_pieces + shape.n_pad_pieces} hashes "
                f"(with padding for merkle tree balance). "
                f"Got: {len(piece_hashes)}"
            )

        return self.hash_root(piece_hashes)


def sort_v2(paths: list[Path]) -> list[Path]:
    """
    V2 paths are sorted in tree order, alphabetically.

    Mostly important for hybrid torrents, because v2 file trees are intrinsically sorted
    by the bencoding format
    """
    return sorted(paths, key=lambda f: f.as_posix())
