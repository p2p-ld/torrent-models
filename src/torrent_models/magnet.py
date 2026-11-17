"""
Magnet link model and renderer!

Originally from sciop.models.magnet
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Self
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from torrent_models.torrent import TorrentBase

MagnetV1Infohash = Annotated[
    str,
    BeforeValidator(lambda x: x.replace("urn:btih:", "")),
    PlainSerializer(lambda x: f"urn:btih:{x}", return_type=str, when_used="always"),
    Field(json_schema_extra={"magnet_key": "xt"}),
]
MagnetV2Infohash = Annotated[
    str,
    BeforeValidator(lambda x: x.replace("urn:btmh:1220", "")),
    PlainSerializer(lambda x: f"urn:btmh:1220{x}", return_type=str, when_used="always"),
    Field(json_schema_extra={"magnet_key": "xt"}),
]


def _range_str(val: str) -> str:
    assert re.fullmatch(r"\d+-\d+", val), "Range string must be in the form of {number}-{number}"
    return val


def _split_list(val: list | str) -> list:
    if isinstance(val, str):
        return val.split(",")
    return val


_RangeStr = Annotated[str, AfterValidator(_range_str)]
MagnetFileSelect = Annotated[
    list[int | _RangeStr],
    BeforeValidator(_split_list),
    PlainSerializer(lambda x: ",".join([str(ix) for ix in x])),
    Field(
        json_schema_extra={"magnet_key": "so"},
    ),
]


QUERY_FRAGMENT = r"(?:\?|&)(?P<key>[\w\.]+)=(?P<value>[^=\?&]+)"


class MagnetLink(BaseModel):
    """
    Parser/serializer for magnet links

    Get the rendered magnet link with :meth:`.render` or by casting to ``str(magnet)``!

    References:
        - https://www.bittorrent.org/beps/bep_0009.html
        - https://www.bittorrent.org/beps/bep_0053.html
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    PATTERN: ClassVar[re.Pattern] = re.compile(rf"magnet:({QUERY_FRAGMENT})+")

    v1_infohash: MagnetV1Infohash | None = None
    v2_infohash: MagnetV2Infohash | None = None
    file_name: str | None = Field(default=None, alias="dn", json_schema_extra={"magnet_key": "dn"})
    size: int | None = Field(default=None, alias="xl", json_schema_extra={"magnet_key": "xl"})
    trackers: list[str] | None = Field(
        default=None, alias="tr", json_schema_extra={"magnet_key": "tr"}
    )
    web_seeds: list[str] | None = Field(
        default=None, alias="ws", json_schema_extra={"magnet_key": "ws"}
    )
    select_files: MagnetFileSelect | None = Field(
        default=None, alias="so", json_schema_extra={"magnet_key": "so"}
    )

    def __str__(self) -> str:
        return self.render()

    @classmethod
    def from_torrent(cls, torrent: TorrentBase, **kwargs: Any) -> MagnetLink:
        """
        Create a magnet link from a Torrent object

        ``**kwargs`` override params derived from the object,
        usually to pass a `file_name` when not read from disk.
        """
        trackers = [tracker for tier in torrent.flat_trackers for tracker in tier]
        base = {
            "v1_infohash": torrent.v1_infohash,
            "v2_infohash": torrent.v2_infohash,
            "file_name": torrent._source_file.name if torrent._source_file else None,
            "size": torrent.total_size,
            "trackers": trackers,
        }

        return MagnetLink(**{**base, **kwargs})

    def render(self) -> str:
        """
        Render as an infohash string!
        """
        value = self.model_dump(exclude_none=True, by_alias=True)

        # infohashes use the same key
        v1 = value.pop("v1_infohash", None)
        v2 = value.pop("v2_infohash", None)
        value["xt"] = [infohash for infohash in [v1, v2] if infohash is not None]

        # sort so that infohashes and trackers come first
        order = ["xt", "tr"] + [k for k in sorted(value.keys()) if k not in ("xt", "tr")]
        value = {k: value[k] for k in order if k in value}

        # urlencode all fields except the infohash
        quoted = {}
        for k, v in value.items():
            if k == "xt":
                quoted[k] = v
            elif isinstance(v, list):
                quoted[k] = [quote_plus(str(item)) for item in v]
            else:
                quoted[k] = quote_plus(str(v))

        # don't quote here to preserve colons in infohashes
        def _no_op(value: str, *args: Any, **kwargs: Any) -> str:
            return value

        query = urlencode(quoted, doseq=True, quote_via=_no_op)
        return "magnet:?" + query

    @classmethod
    def parse(cls, magnet: str) -> MagnetLink:
        kwargs = {}
        assert cls.PATTERN.fullmatch(magnet), f"Does not appear to be a magnet link: {magnet}"
        parsed = urlparse(magnet)
        query = parse_qs(parsed.query)
        assert "xt" in query, "Magnet link has no infohash!"

        # xt needs to be parsed into v1 and v2
        for infohash in query.pop("xt"):
            if "btih" in infohash:
                kwargs["v1_infohash"] = infohash
            elif "btmh" in infohash:
                kwargs["v2_infohash"] = infohash
            else:
                # leave open, valid to have non-bittorrent identifiers here
                continue

        # unlist singletons and merge
        kwargs.update({k: v if len(v) > 1 else v[0] for k, v in query.items()})

        return MagnetLink(**kwargs)

    @classmethod
    def key_to_field(cls) -> dict[str, str]:
        """Mapping between infohash field names and model field names"""
        mapping = {}
        for field_name, field in cls.model_fields.items():
            if "magnet_key" in field.json_schema_extra:
                mapping[field.json_schema_extra["magnet_key"]] = field_name
            else:
                mapping[field_name] = field_name
        return mapping

    @classmethod
    def field_to_key(cls) -> dict[str, str]:
        """Inverse of `key_to_field`"""
        return {v: k for k, v in cls.key_to_field().items()}

    @field_validator("trackers", "web_seeds", mode="before")
    def str_to_list(cls, val: str | list) -> list:
        """If list fields are passed as a string, wrap in a list"""
        if not isinstance(val, list):
            return [val]
        return val

    @model_validator(mode="after")
    def v1_or_v2_infohash(self) -> Self:
        """Should have either the v1 or v2 infohash"""
        assert (
            self.v1_infohash is not None or self.v2_infohash is not None
        ), "Either the v1 or v2 infohash must be present"
        return self
