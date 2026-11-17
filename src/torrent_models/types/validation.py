from dataclasses import dataclass
from typing import Literal, Self, TypedDict

from torrent_models.const import BLOCK_SIZE, MAX_BENCODE_DEPTH


@dataclass(frozen=True)
class LoadLimits:
    """
    Limits on how big a torrent and what it describes can be, checked when it's loaded,
    like libtorrent's ``load_torrent_limits``.

    Every valid torrent can be loaded unless limits are given:
    each limit is ``None`` (no limit) unless it's set.
    A program loading torrents from strangers should set them,
    e.g. to libtorrent's with :meth:`.libtorrent`, in the validation context:

    ```python
    Torrent.read(path, context={"limits": LoadLimits.libtorrent()})
    ```

    :meth:`.Torrent.read` and :meth:`.Torrent.read_stream` also take them as keyword arguments,
    replacing those in the context, like ``Torrent.read(path, max_depth=100)``.

    A torrent outside the limits fails validation, saying which limit it broke.
    """

    max_depth: int | None = None
    """
    How deeply lists and dicts can nest in a torrent file,
    when :meth:`.Torrent.read` and :meth:`.Torrent.read_stream` decode it.
    Without it, nesting tens of thousands deep overflows the stack and crashes the process.

    A v2 file tree is a dict for each element of a path,
    inside the torrent, info and file tree dicts, with the file's own dict at the end,
    so a depth of 100 lets paths be 96 deep, counting the file name.
    pydantic validates the file tree by recursing, and stops at about 98 deep on Windows
    and 254 elsewhere.
    """
    max_buffer_size: int | None = None
    """
    Largest torrent file, in bytes, that :meth:`.Torrent.read` and :meth:`.Torrent.read_stream`
    will read. They raise ValueError for a bigger one, before decoding it.
    """
    max_pieces: int | None = None
    """Most pieces a torrent can have"""
    max_piece_length: int | None = None
    """Longest piece length, in bytes"""
    max_file_size: int | None = None
    """Largest file, in bytes, including padfiles"""
    max_total_size: int | None = None
    """
    Largest total size of a torrent's files, in bytes, including their padding:
    v1 padfiles, and in v2, the rest of the last piece of each file.
    """

    @classmethod
    def libtorrent(cls) -> Self:
        """
        libtorrent's limits, a reasonable choice for a client.
        A torrent within them is one libtorrent would load.

        - ``max_depth``, ``max_buffer_size`` and ``max_pieces`` are the defaults of
          libtorrent's ``load_torrent_limits``.
        - ``max_piece_length``: libtorrent's piece picker can't handle pieces
          of more than 2**15 - 1 blocks, so the longest power of two piece length is 256 MiB.
        - ``max_file_size``: libtorrent indexes a file's merkle tree with an int,
          so a file must have fewer than 2**30 - 1 16 KiB blocks.
        - ``max_total_size``: libtorrent's largest offset into a torrent's data.
        """
        return cls(
            max_depth=MAX_BENCODE_DEPTH,
            max_buffer_size=10_000_000,
            max_pieces=2**21,
            max_piece_length=(2**15 - 1) * BLOCK_SIZE,
            max_file_size=(2**30 - 1) * BLOCK_SIZE - 1,
            max_total_size=2**48 - 1,
        )

    def check(self, piece_length: int, n_pieces: int, total_size: int) -> None:
        """
        Raise ValueError if a torrent with this piece length, this many pieces,
        and this many bytes in total is outside the limits.
        File sizes are checked as each file is validated, see :data:`.FileLength`.
        """
        if self.max_piece_length is not None and piece_length > self.max_piece_length:
            raise ValueError(
                f"piece length {piece_length} is more than max_piece_length, "
                f"{self.max_piece_length}"
            )
        if self.max_total_size is not None and total_size > self.max_total_size:
            raise ValueError(
                f"total size {total_size} is more than max_total_size, {self.max_total_size}"
            )
        if self.max_pieces is not None and n_pieces > self.max_pieces:
            raise ValueError(f"{n_pieces} pieces is more than max_pieces, {self.max_pieces}")


class ValidationContext(TypedDict, total=False):
    """
    Validation Context parameters that affect validation behavior

    Validation behavior can be controlled like this:

    ```python
    Torrent.model_validate(data, context={"padding": "default"})
    ```

    with any of the values described in this typed dict.

    This model is primarily used for documentation,
    because there is not a valid way that i am aware of to annotate the ValidationInfo.context
    dict since it is read-only (so cast can't be used),
    and one can't annotate non-self attributes.
    plz PR if you know how to get mypy to validate with this type.

    References:
        https://docs.pydantic.dev/latest/concepts/validators/#validation-context
    """

    padding: Literal["default", "ignore", "strict", "forbid"]
    """
    Control how padfiles are validated
    
    `'default`': v1-only torrents -> ignore
                 Hybrid torrents -> strict
    `'ignore'`: skip all padfile validation.
    `'strict'`: every file must start at a piece boundary.
    `'forbid'`: no padfiles may be present.

    if we are validating in pydantic's `strict` mode,
    - `'ignore'` is ignored: strict means that the torrent must be as correct as it can be
    - `'strict'` is unchanged, and becomes the default
    - `'forbid'` is unchanged for v1-only: it's strictly valid to forbid padfiles,
      but for hybrid torrents becomes an error: hybrid torrents *must* be padded
      and the padding must be correct.
    """
    padding_path: Literal["default", "strict"]
    """
    BEP0047 recommends that padfiles are named `.pad/{length}`:
    
    > While clients implementing this extensions will have no use for the path of a padding file 
    > it should be included for backwards compatibility since it is a mandatory field in BEP 3.
    > The recommended path is [".pad", "N"] where N is the length of the padding file in base10. 
    > This way clients not aware of this extension will write the padding files 
    > into a single directory, 
    > potentially re-using padding files from other torrents also stored in that directory.
    
    However this is not required, and is often violated. 
    BEP0047 also recommends now requiring `path` at all for padfiles:
    
    > To eventually allow the path field to be omitted clients implementing this BEP 
    > should not require it to be present on padding files.
    
    So the default behavior is to not check the padfile names,
    but passing `strict` here validates they are `[".pad", length]`
    
    References:
        https://www.bittorrent.org/beps/bep_0047.html
    """
    limits: LoadLimits
    """See :class:`.LoadLimits`. Without it, nothing is limited."""
