from pathlib import Path
import uuid
import random
import string
from tqdm import trange

def _get_name(current_dir) -> Path:
    new_file = current_dir / f'{str(uuid.uuid4()).split("-")[0]}'
    while new_file.exists():
        new_file = current_dir / f'{str(uuid.uuid4()).split("-")[0]}'
    return new_file

def generate_humongous_torrent(n: int=200000, descend_p: float = 0.1, ascend_p: float = 0.09) -> None:
    """
    Generates a directory with many files in a deeply nested directory.

    Not versioned because the torrent is humongous
    """
    root = Path(__file__).parent / "__tmp__"
    root.unlink(missing_ok=True)
    root.mkdir()
    current_dir = Path(str(root))
    for _ in trange(n):
        if random.random() < descend_p:
            current_dir = _get_name(current_dir)
            current_dir.mkdir()
        elif random.random() < ascend_p and current_dir != root:
            current_dir = current_dir.parent

        try:
            with open(_get_name(current_dir).with_suffix('.bin'), 'wb') as f:
                f.write(random.randbytes(random.randint(16, 16* (2**10))))
        except OSError as e:
            if 'too long' in str(e):
                current_dir = Path(str(root))
                with open(_get_name(current_dir).with_suffix('.bin'), 'wb') as f:
                    f.write(random.randbytes(random.randint(16, 16 * (2 ** 10))))

if __name__ == "__main__":
    generate_humongous_torrent()


