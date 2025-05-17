import hashlib
from collections import defaultdict
from multiprocessing.pool import AsyncResult
from multiprocessing.pool import Pool as PoolType

from pydantic import field_validator

from torrent_models.compat import get_size
from torrent_models.const import BLOCK_SIZE
from torrent_models.hashing.base import Chunk, Hash, HasherBase
from torrent_models.types import SHA256Hash
from torrent_models.types.v2 import MerkleTree, MerkleTreeShape, V2PieceLength


class V2Hasher(HasherBase):
    piece_length: V2PieceLength

    @field_validator("read_size", mode="after")
    def read_size_is_block_size(self, value: int) -> int:
        assert value == BLOCK_SIZE
        return value

    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        return [pool.apply_async(self._hash_v2, (chunk,))]

    @classmethod
    def hash_root(
        cls,
        hashes: list[bytes],
    ) -> bytes:
        """
        Given hashes of 16KiB leaves, compute their root.
        To compute the items in the piece layers dict,
        pass piece_length / 16KiB leaf hashes at a time.

        References:
            - https://www.bittorrent.org/beps/bep_0052_torrent_creator.py
        """
        assert len(hashes) & (len(hashes) - 1) == 0

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
            file_size = get_size(self.path_base / path)
            shape = MerkleTreeShape(file_size=file_size, piece_length=self.piece_length)
            hash_bytes = [h.hash for h in hashes]
            if len(hash_bytes) < shape.n_blocks + shape.n_pad_blocks:
                leaf_hashes += [bytes(32)] * shape.n_pad_blocks

            piece_hashes = self.hash_pieces(hash_bytes)
            tree.root_hash = tree.get_root_hash(tree.piece_hashes)
            trees.append(tree)

        if len(trees) == 1:
            return trees[0]
        return trees

    def hash_pieces(self, leaf_hashes: list[SHA256Hash], shape: MerkleTreeShape) -> list[bytes]:
        """Compute the piece hashes for the layer dict"""
        if shape.n_pieces <= 1:
            return []

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
        padded with all-zero blocks to have enough blocks for a full piece
        """
        if shape.n_pieces <= 1:
            shape.validate_leaf_count(self.leaf_hashes)
            self.root_hash = self.hash_root(self.leaf_hashes)
            return self.root_hash

        if piece_hashes is None and len(self.piece_hashes) == 0:
            raise ValueError("No precomputed piece hashes and none passed!")
        elif piece_hashes is None:
            piece_hashes = self.piece_hashes

        if len(piece_hashes) == 1:
            return piece_hashes[0]

        if len(piece_hashes) == self.n_pieces and self.n_pad_pieces > 0:
            pad_piece_hash = self.hash_root([bytes(32)] * self.blocks_per_piece)
            piece_hashes = piece_hashes + ([pad_piece_hash] * self.n_pad_pieces)
        elif len(piece_hashes) != self.n_pieces + self.n_pad_pieces:
            raise ValueError(
                f"Expected either {self.n_pieces} (unpadded) piece hashes or "
                f"{self.n_pieces + self.n_pad_pieces} hashes "
                f"(with padding for merkle tree balance). "
                f"Got: {len(piece_hashes)}"
            )

        root_hash = self.hash_root(piece_hashes)
        self.root_hash = root_hash
        return root_hash

    @cached_property
    def file_size(self) -> int:
        return get_size(self.path)
