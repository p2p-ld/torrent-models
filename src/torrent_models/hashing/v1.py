from functools import cached_property
from itertools import count
from multiprocessing.pool import AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import TYPE_CHECKING, cast, overload

from pydantic import PrivateAttr, ValidationInfo, field_validator

from torrent_models.hashing.base import Chunk, Hash, HasherBase
from torrent_models.types.v1 import V1PieceLength

if TYPE_CHECKING:
    from multiprocessing.pool import AsyncResult


class V1Hasher(HasherBase):
    piece_length: V1PieceLength
    _buffer: bytearray = PrivateAttr(default_factory=bytearray)
    _v1_counter: count = PrivateAttr(default_factory=count)
    _last_path: Path | None = None

    @field_validator("read_size", mode="before")
    def read_size_is_piece_length(cls, value: int | None, info: ValidationInfo) -> int:
        """If read_size not passed, make it piece_length"""
        if value is None:
            value = info.data["piece_length"]
        return value

    @field_validator("paths", mode="after")
    def sort_paths(cls, value: list[Path]) -> list[Path]:
        """
        v1 torrents have arbitrary file sorting,
        but we mimick libtorrent/qbittorrent's sort order for consistency's sake
        """
        value = sort_v1(value)
        return value

    @overload
    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]: ...

    @overload
    def update(self, chunk: Chunk, pool: None) -> list[Hash]: ...

    def update(self, chunk: Chunk, pool: PoolType | None = None) -> list[AsyncResult] | list[Hash]:
        return self._update_v1(chunk, pool)

    @cached_property
    def total_hashes(self) -> int:
        return self._v1_total_hashes()

    @overload
    def _update_v1(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]: ...

    @overload
    def _update_v1(self, chunk: Chunk, pool: None) -> list[Hash]: ...

    def _update_v1(self, chunk: Chunk, pool: PoolType | None) -> list[AsyncResult] | list[Hash]:
        # gather v1 pieces until we have blocks_per_piece or reach the end of a file
        # have to annotate as a mixed list here and recast at the end
        # because mypy can't follow the overloads
        res: list[AsyncResult | Hash] = []
        if self._last_path is not None and chunk.path != self._last_path and len(self._buffer) > 0:
            res.extend(self._on_file_end(pool=pool))
        self._last_path = chunk.path

        if len(chunk.chunk) == self.piece_length and not self._buffer:
            # shortcut for when our read_length is piece size -
            # don't copy to buffer if we don't have to
            chunk.idx = next(self._v1_counter)
            if pool:
                res.append(pool.apply_async(self._hash_v1, (chunk, self.path_root)))
            else:
                res.append(self._hash_v1(chunk, self.path_root))
        else:
            # handle file ends, read sizes that are larger/smaller than piece size.
            self._buffer.extend(chunk.chunk)
            while len(self._buffer) >= self.piece_length:
                piece = self._buffer[: self.piece_length]
                del self._buffer[: self.piece_length]
                piece_chunk = Chunk.model_construct(
                    idx=next(self._v1_counter), path=chunk.path, chunk=piece
                )
                if pool:
                    res.append(pool.apply_async(self._hash_v1, (piece_chunk, self.path_root)))
                else:
                    res.append(self._hash_v1(piece_chunk, self.path_root))

        res = cast(list[AsyncResult] | list[Hash], res)
        return res

    @overload
    def _on_file_end(self, pool: PoolType) -> list[AsyncResult]: ...

    @overload
    def _on_file_end(self, pool: None) -> list[Hash]: ...

    def _on_file_end(self, pool: PoolType | None) -> list[AsyncResult] | list[Hash]:
        """Allow hybrid hasher to add padding at file boundaries and submit piece"""
        return []

    @overload
    def _after_read(self, pool: PoolType) -> list[AsyncResult]: ...

    @overload
    def _after_read(self, pool: None) -> list[Hash]: ...

    def _after_read(self, pool: PoolType | None) -> list[AsyncResult] | list[Hash]:
        """Submit the final incomplete piece"""
        if len(self._buffer) > 0:
            self._last_path = cast(Path, self._last_path)
            chunk = Chunk.model_construct(
                idx=next(self._v1_counter), path=self._last_path, chunk=self._buffer
            )
            if pool:
                return [pool.apply_async(self._hash_v1, args=(chunk, self.path_root))]
            else:
                return [self._hash_v1(chunk, self.path_root)]
        else:
            return []


def sort_v1(paths: list[Path]) -> list[Path]:
    """
    v1 sorts top-level files first, then within that division alphabetically
    https://github.com/alanmcgovern/monotorrent/issues/563
    """
    return sorted(paths, key=lambda path: (len(path.parts) != 1, str(path).lower()))
