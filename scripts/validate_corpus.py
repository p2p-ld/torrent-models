"""
Roundtrip a directory of valid torrents to ensure that we correctly read, validate, and write them.
"""

import argparse
from pathlib import Path

import bencode_rs
from _pytest.assertion.util import _compare_eq_dict
from tqdm import tqdm

from torrent_models import Torrent


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory")
    parser.add_argument("-s", "--start", default=0, type=int)
    args = parser.parse_args()
    return args


def files_equal(file1: Path, file2: Path) -> bool:
    data1 = file1.read_bytes()
    data2 = file2.read_bytes()
    if data1 != data2:
        decoded_1 = bencode_rs.bdecode(data1)
        decoded_2 = bencode_rs.bdecode(data2)
        # some torrent creators flatten length-1 lists, others don't - either is fine.
        if (
            (url_list := decoded_1.get(b"url-list"))
            and isinstance(url_list, list)
            and len(url_list) == 1
        ):
            decoded_1[b"url-list"] = url_list[0]
        diff = _compare_eq_dict(decoded_1, decoded_2, lambda x: x, verbose=1)
        if len(diff) > 1:
            breakpoint()


def roundtrip_torrent(path: Path, output_dir: Path):
    output_path = output_dir / path.name
    try:
        t = Torrent.read(path, context={"padding": "ignore"})
        t.write(output_path)
    except Exception as e:
        e = e
        breakpoint()
    files_equal(path, output_dir / path.name)
    output_path.unlink()


def main():
    args = parse_args()
    tmp_dir = Path().cwd() / "__tmp__"
    tmp_dir.mkdir(exist_ok=True)
    torrent_dir = Path(args.directory)
    torrents = sorted(list(torrent_dir.rglob("*.torrent")))
    for torrent in tqdm(torrents[args.start :]):
        try:
            roundtrip_torrent(torrent, tmp_dir)
        except Exception as e:
            raise ValueError(f"{torrent} is invalid") from e


if __name__ == "__main__":
    main()
