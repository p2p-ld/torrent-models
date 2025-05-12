"""
Hybrid v1/v2 torrent creation

This is not a straightforward combination of v1 and v2 hashing
since each version of torrent has different optimization requirements.

Since v1 is just a linear set of hashes, and the pieces are much larger units,
we can read a larger buffer and feed the whole thing into a hashing process at once.
v2 works on 16KiB chunks always, so the tradeoff of reading and processing time is a bit different.

Hybrid torrents require us to do both, as well as generate padfiles,
so we use routines from the v1 and v2 but build on top of them.
"""

from functools import cached_property
from itertools import count
from multiprocessing.pool import AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import Annotated, cast

from annotated_types import Interval
from pydantic import PrivateAttr

from torrent_models.const import BLOCK_SIZE
from torrent_models.hashing.base import Chunk, Hash, HasherBase
from torrent_models.types.v1 import FileItem
from torrent_models.types.v2 import MerkleTree, PieceLayers, V2PieceLength


def add_padfiles(files: list[FileItem], piece_length: int) -> list[FileItem]:
    """
    Modify a v1 file list to intersperse .pad files
    """
    padded = []
    for f in files:
        padded.append(f)
        if f.attr in (b"p", "p"):
            continue
        if (remainder := f.length % piece_length) != 0:
            pad_length = piece_length - remainder
            pad = FileItem(length=pad_length, path=[".pad", str(pad_length)], attr=b"p")
            padded.append(pad)
    return padded


class HybridHasher(HasherBase):
    piece_length: V2PieceLength
    read_size: Annotated[int, Interval(le=BLOCK_SIZE, ge=BLOCK_SIZE)] = BLOCK_SIZE
    """
    How much of a file should be read in a single read call.
    
    For now the hybrid and v2 hashers must read single blocks at a time.
    """

    _v1_chunks: list[Chunk] = PrivateAttr(default_factory=list)
    _last_path: Path | None = None
    _v1_counter: count = PrivateAttr(default_factory=count)

    @cached_property
    def blocks_per_piece(self) -> int:
        return int(self.piece_length / BLOCK_SIZE)

    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        res = [pool.apply_async(self._hash_v2, args=(chunk,))]

        # gather v1 pieces until we have blocks_per_piece or reach the end of a file
        if (
            self._last_path is not None
            and chunk.path != self._last_path
            and len(self._v1_chunks) > 0
        ):
            # just got a piece from the next file
            # if we didn't have a perfectly sized file, pad it and submit hashes

            res.append(self._submit_v1(pool))
            self._v1_chunks = []

        self._v1_chunks.append(chunk)
        self._last_path = chunk.path
        if len(self._v1_chunks) == self.blocks_per_piece:
            res.append(self._submit_v1(pool))
            self._v1_chunks = []

        return res

    def _submit_v1(self, pool: PoolType) -> AsyncResult:
        piece = b"".join([c.chunk for c in self._v1_chunks])

        # append padding
        self._last_path = cast(Path, self._last_path)
        piece = b"".join([piece, bytes(self.piece_length - len(piece))])
        chunk = Chunk.model_construct(idx=next(self._v1_counter), path=self._last_path, chunk=piece)
        return pool.apply_async(self._hash_v1, args=(chunk,))

    def _after_read(self, pool: PoolType) -> list[AsyncResult]:
        """Submit any remaining v1 pieces from the last file"""
        res = []
        if len(self._v1_chunks) > 0:
            res.append(self._submit_v1(pool))
            self._v1_chunks = []
        return res

    def split_v1_v2(
        self,
        hashes: list[Hash],
    ) -> tuple[PieceLayers, list[bytes]]:
        """Split v1 and v2 hashes, returning sorted v1 pieces and v2 piece layers"""
        v1_pieces = [h for h in hashes if h.type == "v1_piece"]
        v1_pieces = sorted(v1_pieces, key=lambda h: h.idx)
        v1_pieces = [h.hash for h in v1_pieces]

        v2_leaf_hashes = [h for h in hashes if h.type == "block"]
        trees = MerkleTree.from_leaf_hashes(v2_leaf_hashes, self.path_base, self.piece_length)
        layers = PieceLayers.from_trees(trees)
        return layers, v1_pieces
