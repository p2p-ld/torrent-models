"""
Mapping between files and the pieces that contain their data.

Access through :attr:`.Torrent.layout`
"""

import posixpath
from bisect import bisect_right
from itertools import accumulate
from math import ceil
from typing import TYPE_CHECKING, cast

from torrent_models.info import InfoDictHybrid, InfoDictV1, InfoDictV2
from torrent_models.types import FileItem, FileTreeItem, PieceLayersType, TorrentVersion
from torrent_models.types.v1 import FileItemRange, V1PieceRange
from torrent_models.types.v2 import V2PieceRange

if TYPE_CHECKING:
    from torrent_models.torrent import Torrent


class FileLayout:
    """
    Where each file's data is within a torrent's pieces.

    - v1: files (including padfiles) are laid end to end and split into pieces,
      so a piece may span several files.
    - v2: each file has its own pieces, indexed from 0 within the file.

    Hybrid torrents support both.
    """

    def __init__(self, torrent: "Torrent"):
        self.torrent = torrent
        self._v1_file_ends: list[int] | None = None

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
        assert self.torrent.torrent_version in (
            TorrentVersion.v1,
            TorrentVersion.hybrid,
        ), "Cannot get v1 piece ranges for v2-only torrents"
        info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)

        if info.files is None:
            if path != info.name:
                raise ValueError(f"file {path} not found in torrent!")
            return [self.v1_piece_range(i) for i in range(len(info.pieces))]

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

        file = info.files[file_idx]
        end = self._get_v1_file_ends()[file_idx]
        if file.length == 0:
            return []
        first_piece = (end - file.length) // info.piece_length
        last_piece = (end - 1) // info.piece_length
        return [self.v1_piece_range(i) for i in range(first_piece, last_piece + 1)]

    def _get_v1_file_ends(self) -> list[int]:
        """Byte offset of the end of each file in the v1 files list, within the whole torrent"""
        if self._v1_file_ends is None:
            info = cast(InfoDictV1 | InfoDictHybrid, self.torrent.info)
            files = cast(list[FileItem], info.files)
            self._v1_file_ends = list(accumulate(f.length for f in files))
        return self._v1_file_ends

    def v2_piece_range(self, path: str, piece_idx: int = 0) -> V2PieceRange:
        """
        Get a v2 piece range from a file path and optional piece index.

        If `piece_idx` is not provided (default to 0)...

        - If the file is larger than the piece length, gets the 0th piece.
        - If the file is smaller than the piece length,
          the range corresponds to the whole file, the hash is the root hash,
          and piece_idx is ignored.
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

        full_path = path if len(flat_files) == 1 else "/".join([info.name, path])

        if root not in piece_layers:
            # smaller then piece_length, piece range is whole file
            return V2PieceRange(
                piece_idx=0,
                path=path,
                range_start=0,
                range_end=flat_files[path]["length"],
                piece_length=info.piece_length,
                file_size=flat_files[path]["length"],
                root_hash=root,
                full_path=full_path,
            )
        else:
            if piece_idx >= len(piece_layers[root]):
                raise IndexError(
                    f"piece index {piece_idx} is out of range for file with "
                    f"{len(piece_layers[root])} pieces"
                )
            return V2PieceRange(
                piece_idx=piece_idx,
                path=path,
                range_start=piece_idx * info.piece_length,
                range_end=min(flat_files[path]["length"], (piece_idx + 1) * info.piece_length),
                piece_length=info.piece_length,
                file_size=flat_files[path]["length"],
                piece_hash=piece_layers[root][piece_idx],
                root_hash=root,
                full_path=full_path,
            )

    def v2_file_pieces(self, path: str) -> list[V2PieceRange]:
        """
        Get all the v2 piece ranges that contain a file's data, in order.

        Files no longer than the piece length have a single range covering the whole file,
        see :meth:`.v2_piece_range`

        Args:
            path (str): Path within the torrent, as in :attr:`.Torrent.files`
        """
        assert self.torrent.torrent_version in (
            TorrentVersion.v2,
            TorrentVersion.hybrid,
        ), "Cannot get v2 piece ranges from a v1-only torrent"
        flat_files = cast(dict[str, FileTreeItem], self.torrent.flat_files)
        if path not in flat_files:
            raise ValueError(f"file {path} not found in torrent!")

        n_pieces = ceil(flat_files[path]["length"] / self.torrent.info.piece_length)
        return [self.v2_piece_range(path, i) for i in range(n_pieces)]
