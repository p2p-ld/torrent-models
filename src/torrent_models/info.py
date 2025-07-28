import hashlib
from math import ceil
from posixpath import join as posixjoin
from typing import Annotated, Any, Self, TypeAlias, cast

import bencode_rs
from annotated_types import Ge, MinLen
from pydantic import BaseModel, Discriminator, Field, Tag, ValidationInfo, model_validator

from torrent_models.base import ConfiguredBase
from torrent_models.types import str_keys
from torrent_models.types.serdes import ByteStr
from torrent_models.types.v1 import FileItem, Pieces, V1PieceLength
from torrent_models.types.v2 import FileTree, FileTreeItem, FileTreeType, V2PieceLength


class InfoDictRoot(ConfiguredBase):
    """Fields shared by v1 and v2 infodicts"""

    name: ByteStr | None = None
    source: ByteStr | None = None

    _total_length: int | None = None

    @property
    def v1_infohash(self) -> str | None:
        return None

    @property
    def v2_infohash(self) -> str | None:
        return None

    @model_validator(mode="before")
    @classmethod
    def keys_as_strings(cls, data: Any) -> Any:
        """
        bencoded data comes as bytes, if we are trying to create directly from a bytestring dict,
        decode to strings first
        """
        if isinstance(data, dict) and any([isinstance(k, bytes) for k in data]):
            data = str_keys(data)
        return data


class InfoDictV1Base(InfoDictRoot):
    pieces: Pieces | None = None
    length: Annotated[int, Ge(0)] | None = None
    files: Annotated[list[FileItem], MinLen(1)] | None = Field(None)
    piece_length: V1PieceLength | None = Field(alias="piece length")

    _v1_infohash: str | None = None

    @property
    def v1_infohash(self) -> str:
        """hex-encoded SHA-1 hash of the infodict"""
        if not self._v1_infohash:
            dumped = self.model_dump(exclude_none=True, by_alias=True)
            bencoded = bencode_rs.bencode(dumped)
            self._v1_infohash = hashlib.sha1(bencoded).hexdigest()
        return self._v1_infohash

    @property
    def total_length(self) -> int:
        """Total length of all files, in bytes"""
        return self._total_length_v1()

    def _total_length_v1(self) -> int:
        if self._total_length is None:
            if self.files:
                total = 0
                for f in self.files:
                    total += f.length

                self._total_length = total
            else:
                self._total_length = cast(int, self.length)
        return self._total_length

    @model_validator(mode="after")
    def disallowed_fields(self) -> Self:
        """
        We allow extra fields, but not those in v2 infodicts, in order to make them discriminable
        """
        if isinstance(self.__pydantic_extra__, dict):
            assert "file tree" not in self.__pydantic_extra__, "V1 Infodicts can't have file_trees"
        return self

    @model_validator(mode="after")
    def expected_n_pieces(self) -> Self:
        """We have the expected number of pieces given the sizes implied by our file dict"""
        if self.pieces is None or self.piece_length is None:
            return self
        n_pieces = ceil(self.total_length / self.piece_length)
        assert n_pieces == len(self.pieces), (
            f"Expected {n_pieces} pieces for torrent with "
            f"total length {self.total_length} and piece_length"
            f"{self.piece_length}"
            f"Got {len(self.pieces)}"
        )
        return self

    @model_validator(mode="after")
    def padfile_alignment(self, info: ValidationInfo) -> Self:
        """
        If padfiles are present in the files list,
        the sum of a file and its padfile's sizes must be a multiple of the piece size.

        .. note:: V1-only vs hybrid differences

            Some clients do not pad every non-aligned file in v1-only torrents,
            which defeats the purpose of padding, but it happens.
            The default behavior for v1-only is to ignore padfile validation.
            To ensure global padding for v1-only torrents, use pydantic's `strict` validation mode,
            or pass `context = {"padding": "strict"}`.

            Hybrid torrents must have their v1 files list padded,
            and the padding must be globally correct.

        .. note:: Possible Validation Variations

            The behavior of this validator can be changed by passing `padding` to the `context`
            argument of `model_validate` -
            See :class:`~torrent_models.types.validation.ValidationContext`

        """
        if not self.files or len(self.files) == 1 or not self.piece_length:
            return self

        # -- settle switching vars --
        strict = info.config and info.config.get("strict", False)
        hybrid = hasattr(self, "file_tree")

        mode = "default" if not info.context else info.context.get("padding", "default")

        if mode == "default":
            mode = "strict" if hybrid else "ignore"

        # -- do the behavior switch --
        if mode == "ignore" and not strict:
            return self

        if mode == "strict":
            fn = self._validate_padding_strict
        elif mode == "forbid":
            fn = self._validate_padding_forbid
        else:
            raise ValueError(f"unknown padfile validation mode: {mode}")

        for first, second in zip(self.files[:-1], self.files[1:]):
            fn(first, second)

        return self

    def _validate_padding_strict(self, first: FileItem, second: FileItem) -> None:
        # only validate when the first file is not a padfile. if the second file is a padfile,
        # we just validated the pair in the last iteration
        if first.is_padfile:
            return

        # if the first file's length is a multiple of the piece length, no padfile is needed.
        self.piece_length = cast(int, self.piece_length)
        if first.length % self.piece_length == 0:
            return

        # we have a file that needs padding, so second file must be a padfile
        # and the sum must round out
        message = (
            "padding mode: strict - every file that is not a multiple of piece_length "
            "must have a padding file that aligns each file with a piece boundary."
        )

        assert second.is_padfile, message
        assert (first.length + second.length) % self.piece_length == 0, message

    def _validate_padding_forbid(self, first: FileItem, second: FileItem) -> None:
        assert (
            not first.is_padfile and not second.is_padfile
        ), "padding mode: forbid - padfiles are forbidden"


class InfoDictV1(InfoDictV1Base):
    """An infodict from a valid V1 torrent"""

    name: ByteStr
    pieces: Pieces
    piece_length: V1PieceLength = Field(alias="piece length")

    @model_validator(mode="after")
    def length_xor_files(self) -> Self:
        """
        There is also a key length or a key files, but not both or neither.
        If length is present then the download represents a single file,
        otherwise it represents a set of files which go in a directory structure.
        """
        assert bool(self.length) != bool(
            self.files
        ), "V1 Torrents must have a `length` or `files`,  but not both."
        return self


class InfoDictV1Create(InfoDictV1Base):
    """v1 Infodict that may or may not have its pieces hashed yet"""

    pass


class InfoDictV2Base(InfoDictRoot):
    meta_version: int = Field(2, alias="meta version")
    file_tree: FileTreeType | None = Field(None, alias="file tree")
    piece_length: V2PieceLength | None = Field(alias="piece length")

    _v2_infohash: str | None = None

    @model_validator(mode="after")
    def disallowed_fields(self) -> Self:
        """
        We allow extra fields, but not those in v1 infodicts, in order to make them discriminable
        """
        if isinstance(self.__pydantic_extra__, dict):
            assert "pieces" not in self.__pydantic_extra__, "V2 Infodicts can't have pieces"
        return self

    @property
    def v2_infohash(self) -> str:
        """hex-encoded SHA-256 hash of the infodict"""
        if self._v2_infohash is None:
            dumped = self.model_dump(exclude_none=True, by_alias=True)
            bencoded = bencode_rs.bencode(dumped)
            self._v2_infohash = hashlib.sha256(bencoded).hexdigest()
        return self._v2_infohash

    @property
    def flat_tree(self) -> dict[str, FileTreeItem]:
        """Flattened file tree! mapping full paths to tree items"""
        if self.file_tree is None:
            return {}
        else:
            return FileTree.flatten_tree(self.file_tree)

    @property
    def total_length(self) -> int:
        """
        Total length of all files, in bytes.
        """
        total_length = 0
        for file in self.flat_tree.values():
            total_length += file["length"]
        return total_length


class InfoDictV2(InfoDictV2Base):
    """An infodict from a valid V2 torrent"""

    name: ByteStr
    piece_length: V2PieceLength = Field(alias="piece length")
    file_tree: FileTreeType = Field(alias="file tree", exclude=False)


class InfoDictV2Create(InfoDictV2Base):
    pass


class InfoDictHybridCreate(InfoDictV1Create, InfoDictV2Create):
    """An infodict of a hybrid torrent that may or may not have its pieces hashed yet"""

    @model_validator(mode="after")
    def disallowed_fields(self) -> Self:
        """hybrids can have any additional fields"""
        return self

    name: ByteStr | None = None
    piece_length: V1PieceLength | V2PieceLength | None = Field(None, alias="piece length")


class InfoDictHybrid(InfoDictV2, InfoDictV1):
    """An infodict of a valid v1/v2 hybrid torrent"""

    piece_length: V2PieceLength = Field(alias="piece length")

    @model_validator(mode="after")
    def disallowed_fields(self) -> Self:
        """hybrids can have any additional fields"""
        return self

    @model_validator(mode="after")
    def expected_n_pieces(self) -> Self:
        """
        We have the expected number of pieces given the sizes implied by our file dict.

        Overrides the v1 to account for expected padding in hybrids
        """
        if self.pieces is None:
            return self
        if self.files is not None:
            n_pieces = ceil(sum([f.length for f in self.files]) / self.piece_length)
        else:
            self.length = cast(int, self.length)
            n_pieces = ceil(self.length / self.piece_length)

        assert n_pieces == len(self.pieces), (
            f"Expected {n_pieces} pieces for hybrid torrent with "
            f"total length {self._total_length_v1()} and piece_length "
            f"{self.piece_length}. "
            f"Got {len(self.pieces)}"
        )
        return self

    @model_validator(mode="after")
    def v1_v2_files_match(self) -> Self:
        """
        From BEP 052:

        > ... the 'pieces' field and 'files' or 'length' in the info dictionary
        > must be generated to describe the same data in the same order.
        > ... Before doing so they must validate that the content
        > (file names, order, piece alignment) is identical.

        file names, sizes, and order must match (ignoring padfiles).
        """
        v2_files = self.flat_tree
        if not self.files:
            v1_files = [FileItem(path=[self.name], length=self.length)]
        else:
            v1_files = [f for f in self.files if not f.is_padfile]

        assert len(v1_files) == len(
            v2_files
        ), "v1 file lists and v2 file trees must have same length"
        for v1_file, v2_item in zip(v1_files, v2_files.items()):
            v2_path, v2_file = v2_item
            v1_posix = posixjoin(*v1_file.path)

            assert v1_posix == v2_path, (
                "v1 file lists and v2 file trees must be in the same order "
                "and have matching path names, excluding v1 padfiles. "
                f"Got:\n"
                f"v1 path: {posixjoin(*v1_file.path)}\n"
                f"v2 path: {v2_path}\n"
            )
            assert v1_file.length == v2_file["length"], (
                "v1 and v2 file lengths must match. Got: \n"
                f"path: {v1_posix}\n"
                f"v1 length: {v1_file.length}\n"
                f"v2 length: {v2_file['length']}"
            )

        return self


def infodict_discriminator(v: Any) -> str | None:
    """
    Discriminator function to use when detecting torrent version,
    and thus which infodict model to validate against.

    Use this instead of standard union discrimination for clearer error messages-
    if there is a validation error in the infodict, since all infodict types will have been tried,
    trivial errors from the two invalid infodict models will also be shown.

    References:
        https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions-with-callable-discriminator
    """
    # leave the `else` off all these switches to return None if nothing is found.
    # this isn't a validation function, it's just to determine the infodict type
    # if we can't do it here, we do it via validation.
    if isinstance(v, dict):
        v1 = "pieces" in v or b"pieces" in v
        v2 = "file tree" in v or b"file tree" in v
        if v1 and v2:
            return "hybrid"
        elif v1:
            return "v1"
        elif v2:
            return "v2"

    elif isinstance(v, BaseModel):
        if isinstance(v, InfoDictHybrid | InfoDictHybridCreate):
            return "hybrid"
        elif isinstance(v, InfoDictV1Base):
            return "v1"
        elif isinstance(v, InfoDictV2Base):
            return "v2"
    return None


InfodictUnionType: TypeAlias = Annotated[
    (
        Annotated[InfoDictV1, Tag("v1")]
        | Annotated[InfoDictV2, Tag("v2")]
        | Annotated[InfoDictHybrid, Tag("hybrid")]
    ),
    Discriminator(infodict_discriminator),
]
