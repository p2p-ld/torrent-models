import multiprocessing as mp
from abc import abstractmethod
from collections import deque
from functools import cached_property
from itertools import count
from math import ceil
from multiprocessing.pool import ApplyResult, AsyncResult
from multiprocessing.pool import Pool as PoolType
from pathlib import Path
from typing import AsyncGenerator, Generic, TypeVar, overload
from typing import Literal as L

from anyio import open_file, run
from pydantic import BaseModel, Field
from tqdm import tqdm

from torrent_models.junkdrawer import DummyPbar, PbarLike
from torrent_models.types import V1PieceLength, V2PieceLength

BLOCK_SIZE = 16 * (2**10)

T = TypeVar("T")
"""Type of completed result of hasher"""


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
    idx: int
    """The index of the block for ordering, may be within-file or across-files"""


async def iter_blocks(path: Path, read_size: int = BLOCK_SIZE) -> AsyncGenerator[Chunk]:
    """Iterate 16KiB blocks"""
    counter = count()
    last_size = read_size
    async with await open_file(path, "rb") as f:
        while last_size == read_size:
            read = await f.read(read_size)
            if len(read) > 0:
                yield Chunk.model_construct(idx=next(counter), path=path, chunk=read)
            last_size = len(read)


class HasherBase(BaseModel, Generic[T]):
    paths: list[Path]
    """
    Relative paths beneath the path base to hash.
    
    Paths should already be sorted in the order they are to appear in the torrent
    """
    path_base: Path
    """Directory containing paths to hash"""
    piece_length: V1PieceLength | V2PieceLength
    n_processes: int = Field(default_factory=mp.cpu_count)
    progress: bool = False
    """Show progress"""
    read_size: int = BLOCK_SIZE
    """
    How much of a file should be read in a single read call.
    """
    memory_limit: int | None = None
    """
    Rough cap on outstanding memory usage (in bytes) - pauses reading more data until
    the number of outstanding chunks to process are smaller than this size
    """

    @abstractmethod
    def update(self, chunk: Chunk, pool: PoolType) -> list[AsyncResult]:
        """
        Update hasher with a new chunk of data, returning a list of AsyncResults to fetch hashes
        """
        pass

    @abstractmethod
    def complete(self, hashes: list[Hash]) -> T:
        """After hashing, do any postprocessing to yield the desired output"""
        pass

    def _after_read(self, pool: PoolType) -> list[AsyncResult]:
        """Optional step after reading completes"""
        return []

    @cached_property
    def total_chunks(self) -> int:
        """Total read_size chunks in all files"""
        total_chunks = 0
        for path in self.paths:
            total_chunks += ceil((self.path_base / path).stat().st_size / self.read_size)
        return total_chunks

    @cached_property
    def total_hashes(self) -> int:
        """Total hashes that need to be computed"""
        return self.total_chunks

    @cached_property
    def max_outstanding_results(self) -> int | None:
        """Total number of async result objects that can be outstanding, to limit memory usage"""
        if self.memory_limit is None:
            return None
        else:
            return self.memory_limit // self.read_size

    async def process_async(self) -> T:
        hashes = await self.hash()
        return self.complete(hashes)

    def process(self) -> T:
        return run(self.process_async)

    async def hash(self) -> list[Hash]:
        """
        Hash all files
        """
        pool = mp.Pool(self.n_processes)
        file_pbar: PbarLike
        read_pbar: PbarLike
        hash_pbar: PbarLike
        if self.progress:
            file_pbar = tqdm(total=len(self.paths), desc="File", position=0)
            read_pbar = tqdm(total=self.total_chunks, desc="Reading Chunk", position=1)
            hash_pbar = tqdm(total=self.total_hashes, desc="Hashing Chunk", position=2)
        else:
            file_pbar = DummyPbar()
            read_pbar = DummyPbar()
            hash_pbar = DummyPbar()

        hashes = []
        results: deque[ApplyResult] = deque()
        try:
            last_path = None
            for path in self.paths:
                if path != last_path:
                    file_pbar.set_description(str(path))

                async for chunk in iter_blocks(self.path_base / path, read_size=self.read_size):
                    read_pbar.update()
                    res = self.update(chunk, pool)
                    results.extend(res)
                    results, hash = self._step_results(results)
                    if hash is not None:
                        hashes.append(hash)
                        hash_pbar.update()

                    if self.max_outstanding_results:
                        while len(results) > self.max_outstanding_results:
                            results, hash = self._step_results(results, block=True)
                            hashes.append(hash)
                            hash_pbar.update()

            results.extend(self._after_read(pool))
            while len(results) > 0:
                results, hash = self._step_results(results, block=True)
                hashes.append(hash)
                hash_pbar.update()

        finally:
            pool.close()
            file_pbar.close()
            read_pbar.close()
            hash_pbar.close()

        return hashes

    @overload
    def _step_results(self, results: deque, block: L[True]) -> tuple[deque, Hash]: ...

    @overload
    def _step_results(self, results: deque, block: L[False]) -> tuple[deque, Hash | None]: ...

    @overload
    def _step_results(self, results: deque) -> tuple[deque, Hash | None]: ...

    def _step_results(self, results: deque, block: bool = False) -> tuple[deque, Hash | None]:
        """Step the outstanding results, yielding a single hash"""
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
