from itertools import count
from multiprocessing.pool import AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import PrivateAttr, ValidationInfo, field_validator

from torrent_models.hashing.base import Chunk, HasherBase
from torrent_models.types.v1 import Pieces, V1PieceLength

if TYPE_CHECKING:
    from multiprocessing.pool import AsyncResult


class V1Hasher(HasherBase):
    piece_length: V1PieceLength
    _buffer: bytearray = PrivateAttr(default_factory=bytearray)
    _v1_counter: count = PrivateAttr(default_factory=count)
    _last_path: Path = PrivateAttr(default_factory=Path)

    @field_validator("read_size", mode="before")
    def read_size_is_piece_length(cls, value: int | None, info: ValidationInfo) -> int:
        """If read_size not passed, make it piece_length"""
        if value is None:
            value = info.data["piece_length"]
        return value

    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        self._last_path = chunk.path
        if len(chunk.chunk) == self.piece_length and not self._buffer:
            # shortcut for when our read_length is piece size -
            # don't copy to buffer if we don't have to
            chunk.idx = next(self._v1_counter)
            return [pool.apply_async(self._hash_v1, (chunk,))]
        else:
            # handle file ends, read sizes that are larger/smaller than piece size.
            self._buffer.extend(chunk.chunk)
            res = []
            while len(self._buffer) >= self.piece_length:
                piece = self._buffer[: self.piece_length]
                del self._buffer[: self.piece_length]
                piece_chunk = Chunk.model_construct(
                    idx=next(self._v1_counter), path=chunk.path, chunk=piece
                )
                res.append(pool.apply_async(self._hash_v1, (piece_chunk,)))
            return res

    def _after_read(self, pool: PoolType) -> list[AsyncResult]:
        """Submit the final incomplete piece"""
        chunk = Chunk.model_construct(
            idx=next(self._v1_counter), path=self._last_path, chunk=self._buffer
        )
        return [pool.apply_async(self._hash_v1, args=(chunk,))]


def hash_pieces(
    paths: list[Path] | Path,
    piece_length: V1PieceLength,
    path_root: Path | None = None,
    n_processes: int | None = None,
    max_memory_size: int | None = None,
    progress: bool = False,
) -> Pieces:
    """
    Given a list of files and piece length, return a concatenated series of SHA1 hashes.

    This does *not* check for correctness of files, e.g. that they have some common root directory.
    It will raise a FileNotFoundError if the file does not exist.

    Args:
        paths (list[Path]): List of files to hash - assumed to already be sorted
        piece_length (V1PieceLength): Length of each piece (in bytes).
        path_root (Path | None): If paths are relative, they are relative to this directory.
            (cwd if None)
        n_processes (int | None): Number of parallel processes to use.
            If `None` , use number of CPUs present
        max_memory_size (int | None): Maximum amount of memory to be used at once (in bytes).
            Not *really* a memory cap, but it prevents us from reading
            more pieces into memory until our outstanding hash queue
            is smaller than max_memory_size / piece_length.
            If None, go hogwild on em (no limit).
        progress (bool): If `True`, progress bar will be displayed
    """
    hasher = V1Hasher(
        paths=paths,
        path_base=path_root,
        piece_length=piece_length,
        n_processes=n_processes,
        progress=progress,
        memory_limit=max_memory_size,
    )
    hashes = hasher.process()
    return [hash.hash for hash in sorted(hashes, key=lambda x: x.idx)]
