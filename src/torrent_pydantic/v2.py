"""
Helpers for v2 torrents
"""

from functools import cached_property
from typing import cast

from pydantic import BaseModel

from torrent_pydantic.types import FileTreeItem, FileTreeType


def _flatten_tree(val: dict, parts: list[str] | list[bytes] | None = None) -> dict:
    # NOT a general purpose dictionary walker.
    out: dict[bytes | str, dict] = {}
    if parts is None:
        parts = []

    for k, v in val.items():
        if k in (b"", ""):
            if isinstance(k, bytes):
                parts = cast(list[bytes], parts)
                out[b"/".join(parts)] = v
            elif isinstance(k, str):
                parts = cast(list[str], parts)
                out["/".join(parts)] = v
        else:
            out.update(_flatten_tree(v, parts + [k]))
    return out


def _unflatten_tree(val: dict) -> dict:
    out: dict[str | bytes, dict] = {}
    for k, v in val.items():
        is_bytes = isinstance(k, bytes)
        parts = k.split(b"/") if is_bytes else k.split("/")
        nested_subdict = out
        for part in parts:
            if part not in nested_subdict:
                nested_subdict[part] = {}
                nested_subdict = nested_subdict[part]
            else:
                nested_subdict = nested_subdict[part]
        if is_bytes:
            nested_subdict[b""] = v
        else:
            nested_subdict[""] = v
    return out


class FileTree(BaseModel):
    """
    A v2 torrent file tree is like

    - `folder/file1.png`
    - `file2.png`

    ```
    {
        "folder": {
            "file1.png": {
                "": {
                    "length": 123,
                    "pieces root": b"<hash>",
                }
            }
        },
        "file2.png": {
            "": {
                "length": 123,
                "pieces root": b"<hash>",
            }
        }
    }
    ```
    """

    tree: FileTreeType

    @classmethod
    def flatten_tree(cls, tree: FileTreeType) -> dict[str, FileTreeItem]:
        """
        Flatten a file tree, mapping each path to the item description
        """
        return _flatten_tree(tree)

    @classmethod
    def unflatten_tree(cls, tree: dict[str, FileTreeItem]) -> FileTreeType:
        """
        Turn a flattened file tree back into a nested file tree
        """
        return _unflatten_tree(tree)

    @cached_property
    def flat(self) -> dict[str, FileTreeItem]:
        """Flattened FileTree"""
        return self.flatten_tree(self.tree)
