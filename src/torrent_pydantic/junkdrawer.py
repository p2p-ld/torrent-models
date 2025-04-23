from typing import Any


class DummyPbar:
    """pbar that does nothing so we i don't get fined by mypy"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update(self, n: int = 1) -> None:
        pass

    def close(self) -> None:
        pass

    def set_description(self, *args: Any, **kwargs: Any) -> None:
        pass
