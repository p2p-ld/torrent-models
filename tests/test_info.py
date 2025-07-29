import pytest
from pydantic import TypeAdapter

from torrent_models import KiB
from torrent_models.info import InfoDictHybrid, InfodictUnionType, InfoDictV1, InfoDictV2
from torrent_models.types import str_keys

v1_infodict = {
    b"name": b"sup.exe",
    b"pieces": b"0" * 20,
    b"piece length": 16 * KiB,
    b"length": 16 * KiB,
}
v2_infodict = {
    b"name": b"sup.exe",
    b"meta version": 2,
    b"piece length": 16 * KiB,
    b"file tree": {b"sup.exe": {b"": {b"length": 16 * KiB, b"pieces root": b"0" * 32}}},
}
hybrid_infodict = {**v1_infodict, **v2_infodict}
infodicts = {"v1": v1_infodict, "v2": v2_infodict, "hybrid": hybrid_infodict}
models = {"v1": InfoDictV1, "v2": InfoDictV2, "hybrid": InfoDictHybrid}


@pytest.mark.parametrize("version", ("v1", "v2", "hybrid"))
@pytest.mark.parametrize("mode", ("bytes", "str", "model"))
def test_infodict_union_discriminator(version, mode):
    info = infodicts[version].copy()
    if mode == "str":
        info = str_keys(info)
    elif mode == "model":
        info = models[version].model_validate(info)

    adapter = TypeAdapter(InfodictUnionType)
    v = adapter.validate_python(info)
    assert isinstance(v, models[version])
