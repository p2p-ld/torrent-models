"""
Load limits, see :class:`.LoadLimits`.
Nothing is limited by default. libtorrent's limits are checked at and just past each limit,
where that's cheap, and limits passed by the caller are checked for both v1 and v2.
"""

import hashlib
import io
from dataclasses import replace
from math import ceil

import bencode_rs
import pytest
from pydantic import ValidationError

from torrent_models import InfoDictV1, InfoDictV2, KiB, LoadLimits, Torrent

LT = LoadLimits.libtorrent()


def _v1_info(lengths: list[int], piece_length: int = 16 * KiB) -> dict:
    files = [{"path": [f"f{i}"], "length": length} for i, length in enumerate(lengths)]
    pieces = bytes(20 * ceil(sum(lengths) / piece_length))
    return {"name": "t", "piece length": piece_length, "pieces": pieces, "files": files}


def _v2_info(lengths: list[int], piece_length: int = 16 * KiB) -> dict:
    root = hashlib.sha256(b"x").digest()
    tree = {f"f{i}": {"": {"length": ln, "pieces root": root}} for i, ln in enumerate(lengths)}
    return {"name": "t", "piece length": piece_length, "meta version": 2, "file tree": tree}


# v2 files are padded to the end of their last piece, like libtorrent counts them
_V2_AT_TOTAL_SIZE = [2**44 - 2**28] * 16 + [15 * 2**28]

AT_LIBTORRENT = [
    pytest.param(InfoDictV1, _v1_info([100], 2**28), id="v1-piece-length"),
    pytest.param(InfoDictV2, _v2_info([100], 2**28), id="v2-piece-length"),
    pytest.param(InfoDictV1, _v1_info([LT.max_file_size], 2**28), id="v1-file-size"),
    pytest.param(InfoDictV2, _v2_info([LT.max_file_size], 2**28), id="v2-file-size"),
    pytest.param(InfoDictV2, _v2_info([LT.max_pieces * 16 * KiB]), id="v2-pieces"),
    pytest.param(InfoDictV2, _v2_info(_V2_AT_TOTAL_SIZE, 2**28), id="v2-total-size"),
]
PAST_LIBTORRENT = [
    pytest.param(InfoDictV1, _v1_info([100], 2**29), "max_piece_length", id="v1-piece-length"),
    pytest.param(InfoDictV2, _v2_info([100], 2**29), "max_piece_length", id="v2-piece-length"),
    pytest.param(
        InfoDictV1, _v1_info([LT.max_file_size + 1], 2**28), "max_file_size", id="v1-file-size"
    ),
    pytest.param(
        InfoDictV2, _v2_info([LT.max_file_size + 1], 2**28), "max_file_size", id="v2-file-size"
    ),
    pytest.param(
        InfoDictV2, _v2_info([LT.max_pieces * 16 * KiB + 1]), "max_pieces", id="v2-pieces"
    ),
    pytest.param(
        InfoDictV2,
        _v2_info([*_V2_AT_TOTAL_SIZE, 1], 2**28),
        "max_total_size",
        id="v2-total-size",
    ),
]


def test_libtorrent_values():
    """libtorrent's load_torrent_limits and file_storage limits, in RC_2_1"""
    assert LT.max_depth == 100
    assert LT.max_buffer_size == 10_000_000
    assert LT.max_pieces == 0x200000
    assert LT.max_piece_length == ((1 << 15) - 1) * 0x4000
    assert LT.max_file_size == (2**31 - 1) // 2 * 0x4000 - 1
    assert LT.max_total_size == (1 << 48) - 1


@pytest.mark.parametrize("model,info,limit", PAST_LIBTORRENT)
def test_no_limits_by_default(model, info, limit):
    """Every valid torrent loads without limits, or with a LoadLimits that sets none"""
    model.model_validate(info)
    model.model_validate(info, context={"limits": LoadLimits()})


@pytest.mark.parametrize("model,info", AT_LIBTORRENT)
def test_at_libtorrent_limits(model, info):
    model.model_validate(info, context={"limits": LT})


@pytest.mark.parametrize("model,info,limit", PAST_LIBTORRENT)
def test_past_libtorrent_limits(model, info, limit):
    with pytest.raises(ValidationError, match=limit):
        model.model_validate(info, context={"limits": LT})


@pytest.mark.parametrize("model,make_info", [(InfoDictV1, _v1_info), (InfoDictV2, _v2_info)])
def test_piece_length(model, make_info):
    limits = {"limits": LoadLimits(max_piece_length=32 * KiB)}
    model.model_validate(make_info([100], piece_length=32 * KiB), context=limits)
    with pytest.raises(ValidationError, match="max_piece_length"):
        model.model_validate(make_info([100], piece_length=64 * KiB), context=limits)


@pytest.mark.parametrize("model,make_info", [(InfoDictV1, _v1_info), (InfoDictV2, _v2_info)])
@pytest.mark.parametrize("piece_length", [0, -16 * KiB])
def test_piece_length_positive(model, make_info, piece_length):
    with pytest.raises(ValidationError):
        model.model_validate({**make_info([100]), "piece length": piece_length})


@pytest.mark.parametrize("model,make_info", [(InfoDictV1, _v1_info), (InfoDictV2, _v2_info)])
def test_file_size(model, make_info):
    limits = {"limits": LoadLimits(max_file_size=100)}
    model.model_validate(make_info([100, 100]), context=limits)
    with pytest.raises(ValidationError, match="max_file_size"):
        model.model_validate(make_info([100, 101]), context=limits)


@pytest.mark.parametrize("model,make_info", [(InfoDictV1, _v1_info), (InfoDictV2, _v2_info)])
def test_negative_file_size(model, make_info):
    with pytest.raises(ValidationError):
        model.model_validate(make_info([100, -1]))


@pytest.mark.parametrize("model,make_info", [(InfoDictV1, _v1_info), (InfoDictV2, _v2_info)])
def test_pieces(model, make_info):
    limits = {"limits": LoadLimits(max_pieces=2)}
    model.model_validate(make_info([32 * KiB]), context=limits)
    with pytest.raises(ValidationError, match="max_pieces"):
        model.model_validate(make_info([32 * KiB + 1]), context=limits)


def test_v2_pieces_per_file():
    """Each v2 file starts on a new piece, so two small files take two pieces"""
    limits = {"limits": LoadLimits(max_pieces=2)}
    InfoDictV2.model_validate(_v2_info([1, 1]), context=limits)
    with pytest.raises(ValidationError, match="max_pieces"):
        InfoDictV2.model_validate(_v2_info([1, 1, 1]), context=limits)


def test_total_size():
    limits = {"limits": LoadLimits(max_total_size=200)}
    InfoDictV1.model_validate(_v1_info([100, 100]), context=limits)
    with pytest.raises(ValidationError, match="max_total_size"):
        InfoDictV1.model_validate(_v1_info([100, 101]), context=limits)

    # v2 files are padded to their pieces
    limits = {"limits": LoadLimits(max_total_size=32 * KiB)}
    InfoDictV2.model_validate(_v2_info([1, 16 * KiB]), context=limits)
    with pytest.raises(ValidationError, match="max_total_size"):
        InfoDictV2.model_validate(_v2_info([1, 1, 1]), context=limits)


def test_raised_limits():
    """Limits can be raised past libtorrent's, and the torrent can still be used"""
    length = LT.max_file_size + 1
    info = _v1_info([length], piece_length=2**29)
    limits = replace(LT, max_piece_length=2**29, max_file_size=length)
    torrent = Torrent.model_validate({"info": info}, context={"limits": limits})
    assert torrent.layout.piece_range(0).ranges[0].length == length


@pytest.mark.parametrize(
    "model,info",
    [(InfoDictV1, _v1_info([0, 0])), (InfoDictV2, _v2_info([0])), (InfoDictV2, _v2_info([]))],
)
def test_empty_torrents_load(model, info):
    """libtorrent refuses torrents with no data, but they're valid"""
    model.model_validate(info, context={"limits": LT})


@pytest.mark.parametrize("pieces", [bytes(20), bytes(60), bytes(41)])
def test_v1_pieces_match_files(pieces):
    """A v1 infodict has 20 bytes of piece hashes for every piece"""
    info = _v1_info([32 * KiB])
    InfoDictV1.model_validate(info)
    with pytest.raises(ValidationError):
        InfoDictV1.model_validate({**info, "pieces": pieces})


def _torrent_bytes(size: int) -> bytes:
    """A valid torrent file, padded with a comment to ``size`` bytes"""
    info = _v1_info([100])
    tdata = bencode_rs.bencode({b"comment": b"", b"info": info})
    comment_size = size - len(tdata)
    comment_size -= len(str(comment_size)) - 1
    tdata = bencode_rs.bencode({b"comment": b"x" * comment_size, b"info": info})
    assert len(tdata) == size
    return tdata


def test_buffer_size_libtorrent():
    context = {"limits": LT}
    Torrent.read_stream(io.BytesIO(_torrent_bytes(LT.max_buffer_size)), context=context)
    with pytest.raises(ValueError, match="max_buffer_size"):
        Torrent.read_stream(io.BytesIO(_torrent_bytes(LT.max_buffer_size + 1)), context=context)
    Torrent.read_stream(io.BytesIO(_torrent_bytes(LT.max_buffer_size + 1)))


def test_buffer_size():
    """A file over the limit is refused before it's decoded"""
    tdata = _torrent_bytes(1000)
    Torrent.read_stream(io.BytesIO(tdata), context={"limits": LoadLimits(max_buffer_size=1000)})
    limits = {"limits": LoadLimits(max_buffer_size=999)}
    with pytest.raises(ValueError, match="max_buffer_size"):
        Torrent.read_stream(io.BytesIO(tdata), context=limits)
    with pytest.raises(ValueError, match="max_buffer_size"):
        Torrent.read_stream(io.BytesIO(b"x" * 1000), context=limits)


def test_no_depth_limit_by_default():
    """Without a depth limit, nesting deeper than libtorrent's is decoded"""
    data = b"d4:info" + b"l" * 200 + b"e" * 200 + b"e"
    with pytest.raises(bencode_rs.BencodeDecodeError):
        Torrent.read_stream(io.BytesIO(data), context={"limits": LT})
    # decodes, then fails validation since the info dict is a list
    with pytest.raises(ValidationError):
        Torrent.read_stream(io.BytesIO(data))


def test_read_passes_limits(tmp_path):
    """Limits in the context passed to read are checked when the torrent is validated"""
    path = tmp_path / "t.torrent"
    path.write_bytes(_torrent_bytes(1000))
    Torrent.read(path, context={"limits": LoadLimits(max_pieces=1)})
    with pytest.raises(ValidationError, match="max_file_size"):
        Torrent.read(path, context={"limits": LoadLimits(max_file_size=99)})
