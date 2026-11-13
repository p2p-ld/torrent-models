"""
Mapping between files and the pieces that contain their data.

Access through :attr:`.Torrent.layout`
"""

import posixpath
from bisect import bisect_right
from itertools import accumulate
from math import ceil
from typing import TYPE_CHECKING, Generic, cast, overload

from torrent_models.info import InfoDictHybrid, InfoDictV1, InfoDictV2, InfoT
from torrent_models.types import (
    FileItem,
    FileTreeItem,
    GenericFileItem,
    PieceLayersType,
    TorrentVersion,
)
from torrent_models.types.v1 import FileItemRange, V1PieceRange
from torrent_models.types.v2 import V2PieceRange

if TYPE_CHECKING:
    from torrent_models.torrent import Torrent


class FileLayout(Generic[InfoT]):  # noqa: UP046 - see InfoT
    """
    Where each file's data is within a torrent's pieces.

    - v1: files (including padfiles) are laid end to end and split into pieces,
      so a piece may span several files.
    - v2: each non-empty file starts on a new piece, so a piece never spans files.
      Pieces are numbered across the whole torrent in file tree order (BEP 52),
      and each v2 piece also has an index within its file.

    Hybrid torrents support both.
    Their padfiles start each file on a new v1 piece, so v1 and v2 piece indices are the same.
    """

    def __init__(self, torrent: "Torrent[InfoT]"):
        self.torrent = torrent
        self._v1_file_ends: list[int] | None = None
        self._v2_file_starts: dict[str, int] | None = None
        self._v2_nonempty_starts: list[int] = []
        self._v2_nonempty_paths: list[str] = []
        self._v2_n_pieces = 0
        self._files: dict[str, GenericFileItem] | None = None
        """:attr:`.Torrent.files` by path"""

    @property
    def n_pieces(self) -> int:
        """Number of pieces in the torrent"""
        if self.torrent.torrent_version == TorrentVersion.v2:
            self._get_v2_file_starts()
            return self._v2_n_pieces
        info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)
        return len(info.pieces)

    def file(self, path: str) -> GenericFileItem:
        """
        A file by its path within the torrent, as in :attr:`.Torrent.files`.
        Raises ValueError if there's no such file.
        """
        if self._files is None:
            self._files = {f.path: f for f in self.torrent.files}
        if path not in self._files:
            raise ValueError(f"file {path} not found in torrent!")
        return self._files[path]

    # see file_pieces for why the overloads overlap
    @overload
    def piece_range(  # type: ignore[overload-overlap]
        self: "FileLayout[InfoDictV2]", piece_idx: int
    ) -> V2PieceRange: ...
    @overload
    def piece_range(self: "FileLayout[InfoDictV1]", piece_idx: int) -> V1PieceRange: ...
    @overload
    def piece_range(self, piece_idx: int) -> V1PieceRange | V2PieceRange: ...
    def piece_range(self, piece_idx: int) -> V1PieceRange | V2PieceRange:
        """
        Get a piece range from its index within the whole torrent.

        Uses v2 piece ranges for v2 and hybrid torrents, and v1 piece ranges for v1 torrents.
        See :meth:`.v1_piece_range` and :meth:`.v2_piece_range_at`
        """
        if self.torrent.torrent_version == TorrentVersion.v1:
            return self.v1_piece_range(piece_idx)
        else:
            return self.v2_piece_range_at(piece_idx)

    # hybrids count as v1 to the type checker, but get v2 ranges here,
    # so the first two overloads overlap with different return types.
    @overload
    def file_pieces(  # type: ignore[overload-overlap]
        self: "FileLayout[InfoDictV2]", path: str
    ) -> list[V2PieceRange]: ...
    @overload
    def file_pieces(self: "FileLayout[InfoDictV1]", path: str) -> list[V1PieceRange]: ...
    @overload
    def file_pieces(self, path: str) -> list[V1PieceRange] | list[V2PieceRange]: ...
    def file_pieces(self, path: str) -> list[V1PieceRange] | list[V2PieceRange]:
        """
        Get all the piece ranges that contain a file's data, in order.

        Uses v2 piece ranges for v2 and hybrid torrents, and v1 piece ranges for v1 torrents.
        See :meth:`.v1_file_pieces` and :meth:`.v2_file_pieces`

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
        """
        if self.torrent.torrent_version == TorrentVersion.v1:
            return self.v1_file_pieces(path)
        else:
            return self.v2_file_pieces(path)

    @overload
    def byte_range_pieces(  # type: ignore[overload-overlap]
        self: "FileLayout[InfoDictV2]", path: str, start: int, end: int
    ) -> list[V2PieceRange]: ...
    @overload
    def byte_range_pieces(
        self: "FileLayout[InfoDictV1]", path: str, start: int, end: int
    ) -> list[V1PieceRange]: ...
    @overload
    def byte_range_pieces(
        self, path: str, start: int, end: int
    ) -> list[V1PieceRange] | list[V2PieceRange]: ...
    def byte_range_pieces(
        self, path: str, start: int, end: int
    ) -> list[V1PieceRange] | list[V2PieceRange]:
        """
        Get the piece ranges that contain bytes ``[start, end)`` of a file, in order.

        Uses v2 piece ranges for v2 and hybrid torrents, and v1 piece ranges for v1 torrents.
        See :meth:`.v1_byte_range_pieces` and :meth:`.v2_byte_range_pieces`

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
            start (int): Byte offset within the file where the range starts
            end (int): Byte offset within the file where the range ends, exclusive
        """
        if self.torrent.torrent_version == TorrentVersion.v1:
            return self.v1_byte_range_pieces(path, start, end)
        else:
            return self.v2_byte_range_pieces(path, start, end)

    def v1_piece_range(self, piece_idx: int) -> V1PieceRange:
        """Get a v1 piece range from the piece index"""
        assert self.torrent.torrent_version in (
            TorrentVersion.v1,
            TorrentVersion.hybrid,
        ), "Cannot get v1 piece ranges for v2-only torrents"
        info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)
        if piece_idx >= len(info.pieces):
            raise IndexError(
                f"Cannot get piece index {piece_idx} for torrent with {len(info.pieces)} pieces"
            )

        start_range = piece_idx * info.piece_length
        end_range = (piece_idx + 1) * info.piece_length

        if info.files is None:
            info.length = cast(int, info.length)
            # single file torrent
            return V1PieceRange(
                piece_idx=piece_idx,
                piece_length=info.piece_length,
                piece_hash=info.pieces[piece_idx],
                ranges=[
                    FileItemRange(
                        path=[info.name],
                        length=info.length,
                        range_start=start_range,
                        range_end=min(info.length, end_range),
                        full_path=info.name,
                    )
                ],
            )

        # first, find the file where the range starts: the first file that ends after it
        ends = self._get_v1_file_ends()
        first_idx = bisect_right(ends, start_range)
        file = info.files[first_idx]
        file_range_start = start_range - (ends[first_idx] - file.length)
        file_range_end = min(file.length, file_range_start + info.piece_length)
        found_len = file_range_end - file_range_start
        ranges = [
            FileItemRange(
                path=file.path,
                attr=file.attr,
                length=file.length,
                range_start=file_range_start,
                range_end=file_range_end,
                full_path="/".join([info.name, *file.path]),
            )
        ]
        file_idx = first_idx + 1

        # then, iterate through files until the range or files are exhausted
        while found_len < info.piece_length and file_idx < len(info.files):
            file = info.files[file_idx]
            file_range_start = 0
            file_range_end = min(file.length, info.piece_length - found_len)

            ranges.append(
                FileItemRange(
                    path=file.path,
                    attr=file.attr,
                    length=file.length,
                    range_start=file_range_start,
                    range_end=file_range_end,
                    full_path="/".join([info.name, *file.path]),
                )
            )
            found_len += file_range_end - file_range_start
            file_idx += 1
        return V1PieceRange(
            piece_idx=piece_idx,
            piece_length=info.piece_length,
            ranges=ranges,
            piece_hash=info.pieces[piece_idx],
        )

    def v1_file_pieces(self, path: str) -> list[V1PieceRange]:
        """
        Get all the v1 piece ranges that contain a file's data, in order.

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
        """
        file_start, file_end = self._v1_file_span(path)
        return self.v1_byte_range_pieces(path, 0, file_end - file_start)

    def v1_byte_range_pieces(self, path: str, start: int, end: int) -> list[V1PieceRange]:
        """
        Get the v1 piece ranges that contain bytes ``[start, end)`` of a file, in order.

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
            start (int): Byte offset within the file where the range starts
            end (int): Byte offset within the file where the range ends, exclusive
        """
        assert self.torrent.torrent_version in (
            TorrentVersion.v1,
            TorrentVersion.hybrid,
        ), "Cannot get v1 piece ranges for v2-only torrents"
        info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)
        file_start, file_end = self._v1_file_span(path)
        _check_byte_range(path, start, end, file_end - file_start)
        if start == end:
            return []

        first_piece = (file_start + start) // info.piece_length
        last_piece = (file_start + end - 1) // info.piece_length
        return [self.v1_piece_range(i) for i in range(first_piece, last_piece + 1)]

    def _v1_file_span(self, path: str) -> tuple[int, int]:
        """Byte offsets of the start and end of a file within the whole v1 torrent"""
        assert self.torrent.torrent_version in (
            TorrentVersion.v1,
            TorrentVersion.hybrid,
        ), "Cannot get v1 piece ranges for v2-only torrents"
        info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)

        if info.files is None:
            if path != info.name:
                raise ValueError(f"file {path} not found in torrent!")
            return 0, cast(int, info.length)

        file_idx = next(
            (
                i
                for i, f in enumerate(info.files)
                if not f.is_padfile and posixpath.join(*f.path) == path
            ),
            None,
        )
        if file_idx is None:
            raise ValueError(f"file {path} not found in torrent!")

        end = self._get_v1_file_ends()[file_idx]
        return end - info.files[file_idx].length, end

    def _get_v1_file_ends(self) -> list[int]:
        """Byte offset of the end of each file in the v1 files list, within the whole torrent"""
        if self._v1_file_ends is None:
            info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)
            files = cast(list[FileItem], info.files)
            self._v1_file_ends = list(accumulate(f.length for f in files))
        return self._v1_file_ends

    def v2_piece_range(self, path: str, file_piece_idx: int = 0) -> V2PieceRange:
        """
        Get a v2 piece range from a file path and the index of the piece within the file.

        If `file_piece_idx` is not provided (default to 0)...

        - If the file is larger than the piece length, gets the file's first piece.
        - If the file is smaller than the piece length,
          the range corresponds to the whole file, the hash is the root hash,
          and file_piece_idx is ignored.

        To get a piece from its index within the whole torrent, see :meth:`.v2_piece_range_at`
        """
        assert self.torrent.torrent_version in (
            TorrentVersion.v2,
            TorrentVersion.hybrid,
        ), "Cannot get v2 piece ranges from a v1-only torrent"

        info = cast(InfoDictV2 | InfoDictHybrid, self.torrent.info)
        flat_files = cast(dict[str, FileTreeItem], self.torrent.flat_files)
        piece_layers = cast(PieceLayersType, self.torrent.piece_layers)

        if path not in flat_files:
            raise ValueError(f"file {path} not found in torrent!")

        root = flat_files[path]["pieces root"]
        first_piece = self._get_v2_file_starts()[path]

        full_path = self.file(path).download_path

        if root not in piece_layers:
            # smaller then piece_length, piece range is whole file
            return V2PieceRange(
                piece_idx=first_piece,
                file_piece_idx=0,
                path=path,
                range_start=0,
                range_end=flat_files[path]["length"],
                piece_length=info.piece_length,
                file_size=flat_files[path]["length"],
                root_hash=root,
                full_path=full_path,
            )
        else:
            if not 0 <= file_piece_idx < len(piece_layers[root]):
                raise IndexError(
                    f"piece index {file_piece_idx} is out of range for file with "
                    f"{len(piece_layers[root])} pieces"
                )
            return V2PieceRange(
                piece_idx=first_piece + file_piece_idx,
                file_piece_idx=file_piece_idx,
                path=path,
                range_start=file_piece_idx * info.piece_length,
                range_end=min(flat_files[path]["length"], (file_piece_idx + 1) * info.piece_length),
                piece_length=info.piece_length,
                file_size=flat_files[path]["length"],
                piece_hash=piece_layers[root][file_piece_idx],
                root_hash=root,
                full_path=full_path,
            )

    def v2_piece_range_at(self, piece_idx: int) -> V2PieceRange:
        """
        Get a v2 piece range from its index within the whole torrent.

        To get a piece from a file path and its index within the file,
        see :meth:`.v2_piece_range`
        """
        starts = self._get_v2_file_starts()
        if not 0 <= piece_idx < self._v2_n_pieces:
            raise IndexError(
                f"Cannot get piece index {piece_idx} for torrent with {self._v2_n_pieces} pieces"
            )
        # the last non-empty file that starts at or before the piece
        path = self._v2_nonempty_paths[bisect_right(self._v2_nonempty_starts, piece_idx) - 1]
        return self.v2_piece_range(path, piece_idx - starts[path])

    def v2_file_pieces(self, path: str) -> list[V2PieceRange]:
        """
        Get all the v2 piece ranges that contain a file's data, in order.

        Files no longer than the piece length have a single range covering the whole file,
        see :meth:`.v2_piece_range`

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
        """
        return self.v2_byte_range_pieces(path, 0, self._v2_file_length(path))

    def v2_byte_range_pieces(self, path: str, start: int, end: int) -> list[V2PieceRange]:
        """
        Get the v2 piece ranges that contain bytes ``[start, end)`` of a file, in order.

        Files no longer than the piece length have a single range covering the whole file,
        see :meth:`.v2_piece_range`

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
            start (int): Byte offset within the file where the range starts
            end (int): Byte offset within the file where the range ends, exclusive
        """
        info = cast(InfoDictV2 | InfoDictHybrid, self.torrent.info)
        _check_byte_range(path, start, end, self._v2_file_length(path))
        if start == end:
            return []

        # every v2 file starts on a new piece
        first_piece = start // info.piece_length
        last_piece = (end - 1) // info.piece_length
        return [self.v2_piece_range(path, i) for i in range(first_piece, last_piece + 1)]

    def _get_v2_file_starts(self) -> dict[str, int]:
        """Index of the first piece of each file within the whole v2 torrent"""
        if self._v2_file_starts is None:
            info = cast(InfoDictV2 | InfoDictHybrid, self.torrent.info)
            flat_files = cast(dict[str, FileTreeItem], self.torrent.flat_files)
            starts = {}
            piece_idx = 0
            for path, item in flat_files.items():
                starts[path] = piece_idx
                if item["length"] > 0:
                    self._v2_nonempty_starts.append(piece_idx)
                    self._v2_nonempty_paths.append(path)
                piece_idx += ceil(item["length"] / info.piece_length)
            self._v2_file_starts = starts
            self._v2_n_pieces = piece_idx
        return self._v2_file_starts

    def _v2_file_length(self, path: str) -> int:
        assert self.torrent.torrent_version in (
            TorrentVersion.v2,
            TorrentVersion.hybrid,
        ), "Cannot get v2 piece ranges from a v1-only torrent"
        flat_files = cast(dict[str, FileTreeItem], self.torrent.flat_files)
        if path not in flat_files:
            raise ValueError(f"file {path} not found in torrent!")
        return flat_files[path]["length"]


def _check_byte_range(path: str, start: int, end: int, length: int) -> None:
    if not 0 <= start <= end <= length:
        raise IndexError(f"byte range [{start}, {end}) is out of range for {path} of size {length}")
