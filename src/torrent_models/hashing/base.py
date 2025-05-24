import asyncio
import hashlib
import multiprocessing as mp
from abc import abstractmethod
from collections import deque
from collections.abc import AsyncGenerator
from functools import cached_property
from itertools import count
from math import ceil
from multiprocessing.pool import ApplyResult, AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import Any, Self, TypeAlias, cast, overload
from typing import Literal as L

from anyio import open_file
from pydantic import BaseModel, Field, model_validator
from tqdm import tqdm

from torrent_models.compat import get_size
from torrent_models.const import BLOCK_SIZE
from torrent_models.types import AbsPath, RelPath, V1PieceLength, V2PieceLength


class Chunk(BaseModel):
    """A single unit of data, usually a 16KiB block, but can be a whole piece e.g. in v1 hashing"""

    path: Path
    """Absolute path"""
    chunk: bytes
    idx: int


class Hash(BaseModel):
    """Hash of a block or piece"""

    type: L["block", "v1_piece", "v2_piece"]
    path: Path
    hash: bytes
    idx: int = Field(
        ...,
        description="""
    The index of the block for ordering.
    
    For v1 hashes, the absolute index of piece across all files.
    For v2 block and piece hashes, index within the given file
    """,
    )


async def iter_blocks(path: Path, read_size: int = BLOCK_SIZE) -> AsyncGenerator[Chunk, None]:
    """Iterate 16KiB blocks"""
    counter = count()
    last_size = read_size
    async with await open_file(path, "rb") as f:
        while last_size == read_size:
            read = await f.read(read_size)
            if len(read) > 0:
                yield Chunk.model_construct(idx=next(counter), path=path, chunk=read)
            last_size = len(read)


class HasherBase(BaseModel):
    paths: list[RelPath]
    """
    Relative paths beneath the path base to hash.
    
    Paths should already be sorted in the order they are to appear in the torrent
    """
    path_root: AbsPath
    """Directory containing paths to hash"""
    piece_length: V1PieceLength | V2PieceLength
    n_processes: int = Field(default_factory=mp.cpu_count)
    progress: bool = False
    """Show progress"""
    read_size: int | None = None
    """
    How much of a file should be read in a single read call.
    
    If None, set to the piece_length
    """
    memory_limit: int | None = None
    """
    Rough cap on outstanding memory usage (in bytes) - pauses reading more data until
    the number of outstanding chunks to process are smaller than this size
    """

    @staticmethod
    def _hash_v1(chunk: Chunk, path_root: Path) -> Hash:
        return Hash.model_construct(
            hash=hashlib.sha1(chunk.chunk).digest(),
            type="v1_piece",
            path=chunk.path.relative_to(path_root),
            idx=chunk.idx,
        )

    @staticmethod
    def _hash_v2(chunk: Chunk, path_root: Path) -> Hash:
        return Hash.model_construct(
            hash=hashlib.sha256(chunk.chunk).digest(),
            type="block",
            path=chunk.path.relative_to(path_root),
            idx=chunk.idx,
        )

    @abstractmethod
    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        """
        Update hasher with a new chunk of data, returning a list of AsyncResults to fetch hashes
        """
        pass

    @model_validator(mode="after")
    def read_size_defaults_piece_size(self) -> Self:
        if not self.read_size:
            self.read_size = self.piece_length
        return self

    def complete(self, hashes: list[Hash]) -> list[Hash]:
        """After hashing, do any postprocessing to yield the desired output"""
        return hashes

    def _after_read(self, pool: PoolType) -> list[AsyncResult]:
        """Optional step after reading completes"""
        return []

    @cached_property
    def file_sizes(self) -> list[tuple[Path, int]]:
        return [(path, get_size(self.path_root / path)) for path in self.paths]

    @cached_property
    def total_chunks(self) -> int:
        """Total read_size chunks in all files"""
        total_chunks = 0
        self.read_size = cast(int, self.read_size)
        for _, size in self.file_sizes:
            total_chunks += ceil(size / self.read_size)
        return total_chunks

    @cached_property
    def total_size(self) -> int:
        return sum([fs[1] for fs in self.file_sizes])

    @cached_property
    def total_hashes(self) -> int:
        """Total hashes that need to be computed"""
        return self.total_chunks

    def _v1_total_hashes(self) -> int:
        return ceil(self.total_size / self.piece_length)

    def _v2_total_hashes(self) -> int:
        """Total hashes that need to be computed"""
        total_blocks = 0
        for _, size in self.file_sizes:
            total_blocks += ceil(size / BLOCK_SIZE)
        return total_blocks

    def _v1_total_hashes_hybrid(self) -> int:
        total_pieces = 0
        for _, size in self.file_sizes:
            total_pieces += ceil(size / self.piece_length)
        return total_pieces

    @cached_property
    def max_outstanding_results(self) -> int | None:
        """Total number of async result objects that can be outstanding, to limit memory usage"""
        if self.memory_limit is None:
            return None
        else:
            self.read_size = cast(int, self.read_size)
            return self.memory_limit // self.read_size

    async def process_async(self) -> list[Hash]:
        hashes = await self.hash()
        return self.complete(hashes)

    def process(self) -> list[Hash]:
        try:
            return asyncio.run(self.process_async())
        except RuntimeError as e:
            if "from a running event loop" in str(e):
                import nest_asyncio  # type: ignore

                nest_asyncio.apply()
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self.process_async())
            else:
                raise e

    async def hash(self) -> list[Hash]:
        """
        Hash all files
        """
        with mp.Pool(self.n_processes) as pool:
            pbars = self._pbars()

            hashes = []
            results: deque[ApplyResult] = deque()
            # if "1_1073741824_equal0" in str(self.path_root):
            #     breakpoint()
            try:
                for path in self.paths:

                    pbars.file.set_description(str(path))
                    self.read_size = cast(int, self.read_size)
                    async for chunk in iter_blocks(self.path_root / path, read_size=self.read_size):
                        pbars.read.update()
                        res = self.update(chunk, pool)
                        results.extend(res)
                        results, hash = self._step_results(results)
                        if hash is not None:
                            hashes.append(hash)
                            pbars.hash.update()

                        if self.max_outstanding_results:
                            while len(results) > self.max_outstanding_results:
                                results, hash = self._step_results(results, block=True)
                                hashes.append(hash)
                                pbars.hash.update()

                    pbars.file.update()

                results.extend(self._after_read(pool))
                while len(results) > 0:
                    results, hash = self._step_results(results, block=True)
                    hashes.append(hash)
                    pbars.hash.update()

            finally:
                pbars.close()

        return hashes

    @overload
    def _step_results(self, results: deque, block: L[True]) -> tuple[deque, Hash]: ...

    @overload
    def _step_results(self, results: deque, block: L[False]) -> tuple[deque, Hash | None]: ...

    @overload
    def _step_results(self, results: deque) -> tuple[deque, Hash | None]: ...

    def _step_results(self, results: deque, block: bool = False) -> tuple[deque, Hash | None]:
        """Step the outstanding results, yielding a single hash"""
        if len(results) == 0:
            return results, None

        res = results.popleft()
        if block:
            return results, res.get()
        else:
            try:
                return results, res.get(timeout=0)
            except mp.TimeoutError:
                # she not done yet
                results.appendleft(res)
                return results, None

    def _pbars(self) -> "_PBars":
        return _PBars(
            dummy=not self.progress,
            file_total=len(self.paths),
            read_total=self.total_chunks,
            hash_total=self.total_hashes,
        )


class DummyPbar:
    """pbar that does nothing so we i don't get fined by mypy"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update(self, n: int = 1) -> None:
        pass

    def close(self) -> None:
        pass

    def set_description(self, *args: Any, **kwargs: Any) -> None:
        pass


PbarLike: TypeAlias = DummyPbar | tqdm


class _PBars:
    """
    Wrapper around multiple pbars, including dummy pbars for when progress is disabled
    """

    def __init__(
        self,
        file_total: int | None = None,
        read_total: int | None = None,
        hash_total: int | None = None,
        dummy: bool = False,
    ):
        self.file: PbarLike
        self.read: PbarLike
        self.hash: PbarLike
        if dummy:
            self.file = DummyPbar()
            self.read = DummyPbar()
            self.hash = DummyPbar()
        else:
            self.file = tqdm(total=file_total, desc="File", position=0)
            self.read = tqdm(total=read_total, desc="Reading Chunk", position=1)
            self.hash = tqdm(total=hash_total, desc="Hashing Chunk", position=2)

    def close(self) -> None:
        self.file.close()
        self.read.close()
        self.hash.close()
