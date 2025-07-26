import pytest
from pydantic_core._pydantic_core import ValidationError

from torrent_models.const import KiB
from torrent_models.info import InfoDictV1Base
from torrent_models.types import FileItem

no_padding = [
    FileItem(path=["no_padding"], length=14 * KiB),
    FileItem(path=["sup"], length=7 * KiB),
]
correct_padding = [
    FileItem(path=["correct"], length=16 * KiB),
    FileItem(path=["hey"], length=14 * KiB),
    FileItem(path=[".pad", str(2 * KiB)], length=2 * KiB, attr=b"p"),
    FileItem(path=["sup"], length=3 * KiB),
    FileItem(path=[".pad", str(13 * KiB)], length=13 * KiB, attr=b"p"),
]
inconsistent_padding = [
    FileItem(path=["inconsistent"], length=5 * KiB),
    FileItem(path=["hey"], length=14 * KiB),
    FileItem(path=[".pad", str(2 * KiB)], length=2 * KiB, attr=b"p"),
    FileItem(path=["sup"], length=3 * KiB),
    FileItem(path=[".pad", str(13 * KiB)], length=13 * KiB, attr=b"p"),
]
incorrect_padding = [
    FileItem(path=["incorrect"], length=16 * KiB),
    FileItem(path=["hey"], length=14 * KiB),
    FileItem(path=[".pad", str(7 * KiB)], length=7 * KiB, attr=b"p"),
    FileItem(path=["sup"], length=14 * KiB),
    FileItem(path=[".pad", str(7 * KiB)], length=7 * KiB, attr=b"p"),
]


padding_cases = (no_padding, correct_padding, inconsistent_padding, incorrect_padding)


@pytest.mark.parametrize(
    "mode,valid",
    [
        ("default", (True, True, True, True)),
        ("strict", (False, True, False, False)),
        ("forbid", (True, False, False, False)),
        ("ignore", (True, True, True, True)),
    ],
)
def test_padding_validation(mode, valid):
    """
    See description of padding modes in ValidationContext typed dict
    """
    for case, is_valid in zip(padding_cases, valid):
        if is_valid:
            InfoDictV1Base.model_validate(
                dict(name="test", files=case, piece_length=16 * KiB), context={"padding": mode}
            )
        else:
            with pytest.raises(ValidationError):
                InfoDictV1Base.model_validate(
                    dict(name="test", files=case, piece_length=16 * KiB), context={"padding": mode}
                )
